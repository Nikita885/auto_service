"""Звонки клиентам: очередь «Кому позвонить» и отметка звонка.

Очередь не хранится — она вычисляется на лету из записей и последних
звонков, как свободное время из графика точки. Таблица очереди
потребовала бы держать её в согласии с каждой сменой статуса, услуги и
времени записи, и рано или поздно показала бы звонок, который уже не
нужен. Храним только факты — журнал звонков (`BookingCall`).

Причины и порядок — решение заказчика (октябрь 2026):

1. скорая запись, где услугу ещё не выбрали («подберите на месте»);
2. «перезвонить в …» — когда подошло время;
3. клиент опаздывает: запись ждёт, а от начала прошло
   `BOOKING_CALL_LATE_MINUTES` минут;
4. запись на завтра, по которой ещё не дозвонились;
5. запись пришла вне рабочих часов точки;
6. клиент не приехал.

Причина снимается звонком после того, как она появилась: «дозвонился»
закрывает её, «перезвонить в …» закрывает и ставит новую — на назначенное
время, «не дозвонился» оставляет в очереди и считается попыткой. У одной
записи в очереди одна строка — по самой срочной причине.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.constants import UserRole
from apps.accounts.models import User
from apps.booking import events
from apps.booking.constants import (
    ACTIVE_BOOKING_STATUSES,
    CALL_PRIORITY,
    BookingStatus,
    CallOutcome,
    CallReason,
)
from apps.booking.models import Booking, BookingCall
from apps.booking.services import booking as booking_service
from apps.catalog.models import ServicePoint
from apps.common.exceptions import NotFoundError, PermissionError_, ValidationError

logger = logging.getLogger(__name__)

#: Итоги, которые снимают причину звонка: клиента услышали или договорились
#: перезвонить. «Не дозвонился» причину не снимает — это попытка.
CLOSING_OUTCOMES = frozenset({CallOutcome.REACHED, CallOutcome.CALLBACK})

#: Сколько секунд второе такое же нажатие считается повтором первого.
#: Мастер с телефоном у уха жмёт «не дозвонился» дважды — в журнале это
#: должна быть одна попытка, а не две.
REPEAT_WINDOW_SECONDS = 10


@dataclass
class QueueItem:
    """Строка очереди «Кому позвонить»."""

    reason: str
    sort_at: datetime
    client: User
    service_point: ServicePoint
    booking: Booking | None = None
    callback: BookingCall | None = None
    last_call: BookingCall | None = None
    attempts: int = 0
    calls: list = field(default_factory=list, repr=False)

    @property
    def priority(self) -> int:
        return CALL_PRIORITY[self.reason]

    @property
    def hint(self) -> str:
        """Что выяснить — одной строкой, чтобы мастер не открывал запись."""
        booking = self.booking
        if self.reason == CallReason.ON_SITE:
            category = booking.category_title if booking else ""
            return f"Подобрать услугу: {category}" if category else "Подобрать услугу"
        if self.reason == CallReason.CALLBACK:
            note = self.callback.note if self.callback else ""
            return note or "Перезвонить, как договорились"
        return {
            CallReason.LATE: "Опаздывает — приедет?",
            CallReason.TOMORROW: "Напомнить о записи на завтра",
            CallReason.OFF_HOURS: "Записался вне рабочих часов — подтвердить",
            CallReason.NO_SHOW: "Не приехал — перезаписать?",
        }.get(self.reason, "")


# ----------------------------------------------------------------- доступ
def _points(staff, point_id=None) -> list[ServicePoint]:
    """Точки, по которым сотрудник видит очередь. Чужая — отказ."""
    qs = ServicePoint.objects.filter(is_active=True)
    allowed = staff.accessible_point_ids()
    if allowed is not None:
        qs = qs.filter(id__in=allowed)
    if point_id:
        try:
            point = ServicePoint.objects.get(pk=point_id)
        except (ServicePoint.DoesNotExist, ValueError, TypeError) as exc:
            raise NotFoundError("Точка не найдена", code="point_not_found") from exc
        if allowed is not None and point.pk not in allowed:
            raise PermissionError_("Это не ваша точка", code="point_not_allowed")
        return [point]
    return list(qs)


def _local_day_start(point: ServicePoint, now: datetime) -> datetime:
    """Начало сегодняшних суток в поясе точки — граница «сегодняшних» записей."""
    local = now.astimezone(point.tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _is_off_hours(point: ServicePoint, moment: datetime) -> bool:
    """Запись пришла, когда точка не работала: ночью или в выходной."""
    local = moment.astimezone(point.tz)
    if not point.is_workday(local.date()):
        return True
    return not (point.opens_at <= local.time() < point.closes_at)


# ----------------------------------------------------------------- очередь
def _closed_since(calls: list[BookingCall], since: datetime) -> tuple[bool, int]:
    """Снята ли причина звонком после `since`, и сколько было попыток."""
    after = [call for call in calls if call.created_at >= since]
    closed = any(call.outcome in CLOSING_OUTCOMES for call in after)
    attempts = sum(1 for call in after if call.outcome == CallOutcome.NO_ANSWER)
    return closed, attempts


def _booking_reasons(
    booking: Booking, now: datetime, late: timedelta
) -> list[tuple[str, datetime, datetime]]:
    """Причины звонить по записи: (причина, с какого момента, ключ сортировки)."""
    point = booking.service_point
    day_start = _local_day_start(point, now)
    reasons = []
    active = booking.status in ACTIVE_BOOKING_STATUSES

    if (
        active
        and booking.service_on_site
        and not booking.items.all()
        and booking.start_at >= day_start
    ):
        reasons.append((CallReason.ON_SITE, booking.created_at, booking.start_at))
    if booking.status == BookingStatus.PENDING and day_start <= booking.start_at <= now - late:
        reasons.append((CallReason.LATE, booking.start_at, booking.start_at))
    if booking.status == BookingStatus.PENDING:
        tomorrow = (now.astimezone(point.tz) + timedelta(days=1)).date()
        if booking.start_at.astimezone(point.tz).date() == tomorrow:
            reasons.append((CallReason.TOMORROW, booking.created_at, booking.start_at))
        if booking.start_at >= now and _is_off_hours(point, booking.created_at):
            reasons.append((CallReason.OFF_HOURS, booking.created_at, booking.created_at))
    if booking.status == BookingStatus.NO_SHOW and booking.start_at >= day_start:
        marked = next(
            (
                log.created_at
                for log in booking.status_logs.all()
                if log.to_status == BookingStatus.NO_SHOW
            ),
            booking.updated_at,
        )
        reasons.append((CallReason.NO_SHOW, marked, booking.start_at))
    return reasons


def _due_callback(calls: list[BookingCall], now: datetime) -> BookingCall | None:
    """Последний звонок — «перезвонить в …», и время уже подошло."""
    if not calls:
        return None
    last = calls[-1]
    if last.outcome == CallOutcome.CALLBACK and last.callback_at <= now:
        return last
    return None


def queue_for(staff, *, point_id=None, now: datetime | None = None) -> list[QueueItem]:
    """Очередь «Кому позвонить» по точкам сотрудника, самое срочное сверху."""
    now = now or timezone.now()
    points = _points(staff, point_id)
    late = timedelta(minutes=settings.BOOKING["CALL_LATE_MINUTES"])
    # Окно, в котором вообще бывают причины звонить: от начала вчерашних
    # суток (запас на пояса) до конца послезавтрашних («запись на завтра»).
    window_start = now - timedelta(days=1, hours=12)
    window_end = now + timedelta(days=2, hours=12)

    bookings = list(
        Booking.objects.filter(
            service_point__in=points, start_at__gte=window_start, start_at__lt=window_end
        )
        .exclude(
            status__in=[
                BookingStatus.COMPLETED,
                BookingStatus.CANCELLED_BY_CLIENT,
                BookingStatus.CANCELLED_BY_MASTER,
            ]
        )
        .select_related("service_point", "service_category", "user")
        .prefetch_related("items", "status_logs")
    )
    calls_by_booking: dict = {}
    for call in (
        BookingCall.objects.filter(booking__in=bookings)
        .select_related("actor")
        .order_by("created_at")
    ):
        calls_by_booking.setdefault(call.booking_id, []).append(call)

    items: list[QueueItem] = []
    for booking in bookings:
        calls = calls_by_booking.get(booking.pk, [])
        candidates: list[QueueItem] = []
        callback = _due_callback(calls, now)
        if callback is not None:
            candidates.append(
                QueueItem(
                    reason=CallReason.CALLBACK,
                    sort_at=callback.callback_at,
                    client=booking.user,
                    service_point=booking.service_point,
                    booking=booking,
                    callback=callback,
                )
            )
        for reason, since, sort_at in _booking_reasons(booking, now, late):
            closed, attempts = _closed_since(calls, since)
            if not closed:
                candidates.append(
                    QueueItem(
                        reason=reason,
                        sort_at=sort_at,
                        client=booking.user,
                        service_point=booking.service_point,
                        booking=booking,
                        attempts=attempts,
                    )
                )
        if candidates:
            # У записи одна строка — по самой срочной причине.
            best = min(candidates, key=lambda item: item.priority)
            best.last_call = calls[-1] if calls else None
            best.calls = calls
            items.append(best)

    items.extend(_client_callbacks(points, now))
    items.sort(key=lambda item: (item.priority, item.sort_at))
    return items


def _client_callbacks(points, now: datetime) -> list[QueueItem]:
    """«Перезвонить в …», назначенные из карточки клиента, без записи."""
    calls = (
        BookingCall.objects.filter(booking__isnull=True, service_point__in=points)
        .select_related("client", "service_point", "actor")
        .order_by("created_at")
    )
    last_by_client: dict = {}
    for call in calls:
        last_by_client[(call.client_id, call.service_point_id)] = call
    return [
        QueueItem(
            reason=CallReason.CALLBACK,
            sort_at=call.callback_at,
            client=call.client,
            service_point=call.service_point,
            callback=call,
            last_call=call,
        )
        for call in last_by_client.values()
        if call.outcome == CallOutcome.CALLBACK and call.callback_at <= now
    ]


# ------------------------------------------------------------------ звонок
def _client(client_id) -> User:
    try:
        return User.objects.get(pk=client_id, role=UserRole.CLIENT)
    except (User.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Клиент не найден", code="client_not_found") from exc


def _check_outcome(outcome: str, callback_at: datetime | None, now: datetime) -> None:
    if outcome not in CallOutcome.values:
        raise ValidationError("Неизвестный итог звонка", code="call_outcome_invalid")
    if outcome == CallOutcome.CALLBACK:
        if callback_at is None:
            raise ValidationError(
                "Когда перезвонить? Укажите время", code="call_callback_time_required"
            )
        if callback_at <= now:
            raise ValidationError(
                "Перезвонить можно только в будущем", code="call_callback_time_in_past"
            )
    elif callback_at is not None:
        raise ValidationError(
            "Время «перезвонить» — только для итога «перезвонить»",
            code="call_callback_time_unexpected",
        )


@transaction.atomic
def log_call(
    staff,
    *,
    booking_id=None,
    client_id=None,
    point_id=None,
    outcome: str,
    reason: str = CallReason.OTHER,
    note: str = "",
    callback_at: datetime | None = None,
) -> BookingCall:
    """Отметить звонок: по записи или, из карточки, по клиенту и точке.

    Строка записи (или клиента) берётся под блокировку: два быстрых
    нажатия выстраиваются в очередь, и второе видит первое — повтор в
    пределах `REPEAT_WINDOW_SECONDS` возвращает уже сохранённый звонок.
    """
    now = timezone.now()
    _check_outcome(outcome, callback_at, now)
    if reason not in CallReason.values:
        raise ValidationError("Неизвестная причина звонка", code="call_reason_invalid")

    if booking_id:
        booking = booking_service.get_for_master(staff, booking_id)
        booking = (
            Booking.objects.select_for_update()
            .select_related("user", "service_point")
            .get(pk=booking.pk)
        )
        client, point = booking.user, booking.service_point
        same = BookingCall.objects.filter(booking=booking)
    else:
        if not point_id:
            raise ValidationError("Не выбрана точка", code="point_required")
        point = _points(staff, point_id)[0]
        client = User.objects.select_for_update().get(pk=_client(client_id).pk)
        booking = None
        same = BookingCall.objects.filter(booking__isnull=True, client=client, service_point=point)

    repeat = same.filter(
        actor=staff,
        outcome=outcome,
        note=note.strip(),
        callback_at=callback_at,
        created_at__gte=now - timedelta(seconds=REPEAT_WINDOW_SECONDS),
    ).first()
    if repeat is not None:
        return repeat

    call = BookingCall.objects.create(
        client=client,
        booking=booking,
        service_point=point,
        reason=reason,
        outcome=outcome,
        callback_at=callback_at,
        note=note.strip(),
        actor=staff,
    )
    transaction.on_commit(lambda: events.publish_call(call))
    logger.info("Звонок %s: %s", booking.code if booking else "без записи", outcome)
    return call


def booking_journal(staff, booking_id) -> list[BookingCall]:
    """Журнал звонков по записи — новые сверху."""
    booking = booking_service.get_for_master(staff, booking_id)
    return list(booking.calls.select_related("actor").order_by("-created_at"))


def client_journal(staff, client_id) -> list[BookingCall]:
    """Журнал звонков клиенту по точкам сотрудника — новые сверху.

    Чужие точки не показываем: мастеру одной точки незачем знать, о чём
    с клиентом говорили на другой.
    """
    client = _client(client_id)
    calls = BookingCall.objects.filter(client=client).select_related(
        "actor", "booking", "service_point"
    )
    allowed = staff.accessible_point_ids()
    if allowed is not None:
        calls = calls.filter(service_point_id__in=allowed)
    return list(calls.order_by("-created_at"))
