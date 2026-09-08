"""Расчёт свободного времени.

Слоты не хранятся в базе — они выводятся из графика точки. Таблица слотов
потребовала бы генерации вперёд, чистки и синхронизации при смене графика;
вычисление на лету всегда согласовано с настройками точки.

Занятость слота = активные записи + живые черновики, которые этот слот
держат. Именно второе слагаемое не даёт двум клиентам выбрать последнее
свободное время одновременно.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from apps.booking.constants import ACTIVE_BOOKING_STATUSES
from apps.booking.models import Booking, BookingDraft
from apps.catalog.models import ServicePoint
from apps.common.exceptions import ConflictError, ValidationError


@dataclass(frozen=True)
class Slot:
    start_at: datetime
    end_at: datetime
    local_time: str
    free_posts: int


def _horizon_bounds() -> tuple[date, date]:
    today = timezone.localdate()
    return today, today + timedelta(days=settings.BOOKING["HORIZON_DAYS"])


def _earliest_allowed_start() -> datetime:
    return timezone.now() + timedelta(minutes=settings.BOOKING["MIN_LEAD_MINUTES"])


def _grid(point: ServicePoint, day: date) -> list[datetime]:
    """Сетка стартов слотов на день в UTC. Пустая, если день нерабочий."""
    if not point.is_workday(day):
        return []

    opens = point.local_datetime(day, point.opens_at)
    closes = point.local_datetime(day, point.closes_at)
    if closes <= opens:  # график через полночь не поддерживаем осознанно
        return []

    step = timedelta(minutes=point.slot_minutes)
    starts: list[datetime] = []
    cursor = opens
    while cursor + step <= closes:
        starts.append(cursor.astimezone(UTC))
        cursor += step
    return starts


def occupancy(
    point: ServicePoint,
    since: datetime,
    until: datetime,
    *,
    exclude_draft_id=None,
) -> Counter:
    """Сколько постов занято в каждом слоте интервала."""
    taken: Counter = Counter()

    booked = (
        Booking.objects.filter(
            service_point=point,
            status__in=ACTIVE_BOOKING_STATUSES,
            start_at__gte=since,
            start_at__lt=until,
        )
        .values("start_at")
        .annotate(n=Count("id"))
    )
    for row in booked:
        taken[row["start_at"]] += row["n"]

    held = (
        BookingDraft.objects.alive()
        .filter(
            service_point=point,
            slot_start__gte=since,
            slot_start__lt=until,
        )
        .exclude(pk=exclude_draft_id)
        .values("slot_start")
        .annotate(n=Count("id"))
    )
    for row in held:
        taken[row["slot_start"]] += row["n"]

    return taken


def build_slots(
    point: ServicePoint, day: date, *, exclude_draft_id=None
) -> list[Slot]:
    """Свободные слоты точки на день. Занятые и прошедшие не возвращаются."""
    starts = _grid(point, day)
    if not starts:
        return []

    min_start = _earliest_allowed_start()
    step = timedelta(minutes=point.slot_minutes)
    taken = occupancy(
        point, starts[0], starts[-1] + step, exclude_draft_id=exclude_draft_id
    )

    slots: list[Slot] = []
    for start in starts:
        if start < min_start:
            continue
        free = point.posts_count - taken.get(start, 0)
        if free <= 0:
            continue
        slots.append(
            Slot(
                start_at=start,
                end_at=start + step,
                local_time=start.astimezone(point.tz).strftime("%H:%M"),
                free_posts=free,
            )
        )
    return slots


def available_days(point: ServicePoint) -> list[date]:
    """Дни в пределах горизонта, где есть хотя бы один свободный слот."""
    start, end = _horizon_bounds()
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if build_slots(point, cursor):
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def validate_slot(
    point: ServicePoint, start_at: datetime, *, exclude_draft_id=None
) -> tuple[datetime, datetime]:
    """Проверить, что в слот можно записаться. Вернуть (начало, конец) в UTC.

    Вызывается дважды: при выборе времени и повторно при подтверждении,
    потому что между этими шагами слот мог занять кто-то другой.
    """
    if timezone.is_naive(start_at):
        raise ValidationError("Время слота должно быть с часовым поясом",
                              code="slot_naive_datetime")

    start_at = start_at.astimezone(UTC)
    step = timedelta(minutes=point.slot_minutes)

    if start_at < _earliest_allowed_start():
        raise ValidationError(
            "Слишком поздно: записаться можно минимум за "
            f"{settings.BOOKING['MIN_LEAD_MINUTES']} минут",
            code="slot_too_soon",
        )

    horizon_end = timezone.localdate() + timedelta(
        days=settings.BOOKING["HORIZON_DAYS"] + 1
    )
    local_day = start_at.astimezone(point.tz).date()
    if local_day >= horizon_end:
        raise ValidationError(
            f"Запись открыта на {settings.BOOKING['HORIZON_DAYS']} дней вперёд",
            code="slot_beyond_horizon",
        )

    if start_at not in set(_grid(point, local_day)):
        raise ValidationError(
            "Такого слота нет в расписании точки", code="slot_not_in_schedule"
        )

    taken = occupancy(
        point, start_at, start_at + step, exclude_draft_id=exclude_draft_id
    )
    if point.posts_count - taken.get(start_at, 0) <= 0:
        raise ConflictError("Это время уже заняли", code="slot_taken")

    return start_at, start_at + step
