"""Обмен записями с «1С:Автосервисом».

Обмен начинает 1С: она стоит в локальной сети сервиса, и сайт до неё не
достучится, а она до сайта — да. Один цикл обмена — три запроса:

1. `pending` — записи, которых 1С ещё не видела или которые с тех пор
   менялись на сайте. Каждая — целиком, снимком.
2. `ack` — 1С записала их в заявки на ремонт и вернула номер и версию
   заявки.
3. `apply_changes` — что сделали в 1С: перенесли или отменили заявку,
   создали по ней заказ-наряд, закрыли его, пробили чек. Сайт переводит
   запись по своим правилам — теми же функциями, что и панель мастера.

Правила записи живут на сайте. Если правку из 1С сайт принять не может
(время занято, запись уже закрыта), она не применяется, а запись уходит
в 1С заново — заявка вернётся к состоянию сайта, оператор увидит причину.
Иначе сайт и 1С разошлись бы молча.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.accounts.constants import UserRole
from apps.accounts.models import User
from apps.booking.constants import ACTIVE_BOOKING_STATUSES, BookingStatus
from apps.booking.models import Booking
from apps.booking.services import booking as booking_service
from apps.catalog.models import Service
from apps.common.exceptions import DomainError, UnavailableError, ValidationError
from apps.onec.models import BookingSync

logger = logging.getLogger(__name__)

#: Короче — ключ подбирается перебором; длинный ключ ничего не стоит.
MIN_KEY_LENGTH = 32

#: Состояния заказ-наряда (справочник `асСостоянияЗаказНарядов`), после
#: которых работы сделаны и запись на сайте закрывается.
DONE_ORDER_STATES = frozenset({"Выполнен", "Закрыт"})

#: Формат времени для 1С: местное время точки без пояса. В 1С у дат пояса
#: нет, а заявку оператор читает по часам на стене сервиса.
LOCAL_FORMAT = "%Y-%m-%dT%H:%M:%S"


# ------------------------------------------------------------------ доступ
def actor() -> User:
    """Сотрудник, от имени которого 1С меняет записи.

    Отдельная учётка, а не «никто»: в истории записи видно, что перенос
    или отмена пришли из 1С, а права точек работают как у мастера —
    мастеру одной точки 1С не покажет записи другой.
    """
    phone = settings.ONEC["USER_PHONE"]
    user = None
    if phone:
        user = User.objects.filter(
            phone=phone, is_active=True, role__in=(UserRole.MASTER, UserRole.ADMIN)
        ).first()
    if user is None:
        raise UnavailableError(
            "Не настроена учётная запись 1С на сайте (ONEC_USER_PHONE)",
            code="onec_user_missing",
        )
    return user


def key_is_usable(key: str) -> bool:
    return len(key) >= MIN_KEY_LENGTH


# ------------------------------------------------------------------ выгрузка
def version_of(booking: Booking) -> str:
    return booking.updated_at.isoformat()


def _parse_version(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Неверная версия записи", code="onec_bad_version") from exc
    if timezone.is_naive(parsed):
        raise ValidationError("Версия записи без пояса", code="onec_bad_version")
    return parsed


def _visible(user: User):
    queryset = Booking.objects.all()
    allowed = user.accessible_point_ids()
    if allowed is not None:
        queryset = queryset.filter(service_point_id__in=allowed)
    return queryset


def pending(user: User, *, limit: int | None = None) -> tuple[list[Booking], bool]:
    """Записи, которые надо отдать в 1С, — самые давние правки первыми.

    Что 1С ещё не видела, отдаём только живым: запись, которую создали и
    отменили до включения обмена, в 1С была бы пустой закрытой заявкой.
    Старое не тянем вовсе (`EXPORT_DAYS_BACK`): включили обмен — в 1С
    поедут сегодняшние и будущие записи, а не история за годы.
    """
    limit = limit or settings.ONEC["BATCH_SIZE"]
    since = timezone.now() - timedelta(days=settings.ONEC["EXPORT_DAYS_BACK"])
    never = Q(onec_sync__isnull=True) | Q(onec_sync__exported_version__isnull=True)
    queryset = (
        _visible(user)
        .filter(start_at__gte=since)
        .filter(
            (never & Q(status__in=ACTIVE_BOOKING_STATUSES))
            | Q(updated_at__gt=F("onec_sync__exported_version"))
        )
        .select_related("service_point", "service_category", "user", "car", "onec_sync")
        .prefetch_related("items")
        .order_by("updated_at", "id")
    )
    rows = list(queryset[: limit + 1])
    return rows[:limit], len(rows) > limit


def linked(user: User) -> list[str]:
    """Записи, заявки которых 1С должна сверять с сайтом.

    1С сама не отличит заявку с сайта от заведённой руками — список
    даёт сайт: всё уже выгруженное, что ещё живо или менялось недавно.
    Закрытые записи остаются в списке ради оплаты: чек часто пробивают
    после того, как мастер нажал «Выполнено» на сайте.
    """
    since = timezone.now() - timedelta(days=settings.ONEC["EXPORT_DAYS_BACK"] + 1)
    ids = (
        _visible(user)
        .filter(onec_sync__exported_at__isnull=False)
        .filter(Q(status__in=ACTIVE_BOOKING_STATUSES) | Q(start_at__gte=since))
        .order_by("start_at")
        .values_list("id", flat=True)[: settings.ONEC["LINKED_LIMIT"]]
    )
    return [str(pk) for pk in ids]


def local(booking: Booking, value: datetime) -> str:
    return value.astimezone(booking.service_point.tz).strftime(LOCAL_FORMAT)


def snapshot(booking: Booking) -> dict:
    """Запись так, как её заводит 1С: заявка, клиент, машина, позиции."""
    point = booking.service_point
    car = booking.car
    sync = getattr(booking, "onec_sync", None)
    return {
        "id": str(booking.pk),
        "version": version_of(booking),
        "code": booking.code,
        "status": booking.status,
        "status_title": booking.get_status_display(),
        "start": local(booking, booking.start_at),
        "end": local(booking, booking.end_at),
        "created_at": local(booking, booking.created_at),
        "point": {"id": str(point.pk), "name": point.name, "address": point.address},
        "client": {
            "id": str(booking.user_id),
            "name": booking.client_name,
            "phone": booking.client_phone,
        },
        "car": {
            "title": booking.car_model,
            "plate": booking.car_plate,
            "vin": car.vin if car else "",
            "year": car.year if car else None,
            "mileage": car.mileage if car else None,
        },
        "category": booking.category_title,
        "service_title": booking.service_title,
        "on_site": booking.service_on_site,
        "services": [
            {
                "id": str(item.service_id),
                "title": item.title,
                "category": item.category_title,
                "price": str(item.price),
                "material_price": str(item.material_price),
                "quantity": item.quantity,
            }
            for item in booking.items.all()
        ],
        "total_price": str(booking.total_price),
        "final_price": None if booking.final_price is None else str(booking.final_price),
        "points_spent": str(booking.points_spent),
        "comment": booking.client_comment,
        "cancel_reason": booking.cancel_reason,
        "request_number": sync.request_number if sync else "",
    }


def _sync_for(booking: Booking) -> BookingSync:
    sync, _ = BookingSync.objects.select_for_update().get_or_create(booking=booking)
    return sync


@transaction.atomic
def ack(user: User, items: list[dict]) -> int:
    """1С записала заявки — больше эти версии записей не отдаём.

    Ошибку 1С (не нашёлся цех, не записался документ) тоже подтверждаем,
    но с текстом: иначе одна неудачная запись выходила бы первой в каждом
    обмене и рано или поздно заняла бы всю пачку. Повтор — когда запись
    поменяется на сайте или когда её выгрузят заново (`resend`).
    """
    accepted = 0
    visible = _visible(user)
    for item in items:
        booking = visible.filter(pk=item["id"]).first()
        if booking is None:
            continue
        version = _parse_version(item["version"])
        sync = _sync_for(booking)
        # Подтверждение старой версии не должно затереть свежую: два
        # обмена могли разойтись, и тогда новая правка не уехала бы.
        if sync.exported_version is None or version > sync.exported_version:
            sync.exported_version = version
        sync.exported_at = timezone.now()
        if item.get("request_number"):
            sync.request_number = item["request_number"][:32]
        if item.get("request_version"):
            sync.request_version = item["request_version"][:64]
        _set_error(sync, item.get("error") or "")
        sync.save()
        accepted += 1
    return accepted


@transaction.atomic
def resend(user: User, booking_id) -> BookingSync:
    """Выгрузить запись в 1С заново — после того как поправили причину ошибки."""
    booking = booking_service.get_for_master(user, booking_id)
    sync = _sync_for(booking)
    sync.exported_version = None
    sync.save(update_fields=["exported_version", "updated_at"])
    return sync


def _set_error(sync: BookingSync, text: str) -> None:
    sync.last_error = text[:500]
    sync.error_at = timezone.now() if text else None


# ------------------------------------------------------------------ из 1С
def _parse_local(booking: Booking, value: str) -> datetime:
    try:
        parsed = datetime.strptime(value[:19], LOCAL_FORMAT)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Неверное время заявки", code="onec_bad_time") from exc
    return parsed.replace(tzinfo=booking.service_point.tz)


def _service_from_lines(booking: Booking, lines: list[dict]):
    """Услуга сайта по строке заказ-наряда — для записи «подберите на месте».

    Без услуги сайт запись не закроет: нечего списать с остатка. В 1С
    работу оператор уже выбрал — ищем её в каталоге точки по названию.
    """
    names = [(line.get("name") or "").strip() for line in lines]
    # Сравниваем в Python, а не `iexact`: SQLite не знает регистра
    # кириллицы, а оператор 1С наберёт «ЗАМЕНА МАСЛА» или лишний пробел.
    catalog = {
        _plain(service.name): service.pk
        for service in Service.objects.filter(
            category__service_point=booking.service_point, is_active=True
        ).order_by("-category__sort_order", "-sort_order")
    }
    for name in filter(None, names):
        if _plain(name) in catalog:
            return catalog[_plain(name)]
    raise ValidationError(
        "В каталоге точки нет услуги из заказ-наряда — выберите услугу записи на сайте",
        code="onec_service_not_found",
        details={"lines": names},
    )


def _plain(name: str) -> str:
    return " ".join(name.split()).casefold()


def _order_done(order: dict) -> bool:
    return (order.get("state") or "") in DONE_ORDER_STATES or bool(order.get("receipt_number"))


def _apply_one(user: User, item: dict) -> list[str]:
    """Перевести запись по правкам из 1С. Вернуть, что сделали."""
    booking = booking_service.get_for_master(user, item["id"])
    sync = _sync_for(booking)
    request = item.get("request") or {}
    order = item.get("order") or {}
    done: list[str] = []

    request_changed = bool(request) and request.get("version", "") != sync.request_version
    order_changed = bool(order) and order.get("version", "") != sync.order_version

    if order:
        sync.order_ref = order.get("ref") or None
        sync.order_number = (order.get("number") or "")[:32]
        sync.order_state = (order.get("state") or "")[:64]
        sync.order_total = order.get("total")
        sync.paid_total = order.get("paid_total")
        sync.receipt_number = (order.get("receipt_number") or "")[:32]
        if order.get("paid_at"):
            sync.paid_at = sync.paid_at or _parse_local(booking, order["paid_at"])
    if request.get("number"):
        sync.request_number = request["number"][:32]

    if request_changed and booking.status in ACTIVE_BOOKING_STATUSES:
        if request.get("deleted"):
            booking_service.cancel_by_master(
                user, booking.pk, reason=f"Отменена в 1С (заявка {sync.request_number})"
            )
            done.append("cancelled")
        elif request.get("start") and booking.status == BookingStatus.PENDING:
            start_at = _parse_local(booking, request["start"])
            if start_at != booking.start_at:
                booking_service.edit_by_master(user, booking.pk, start_at=start_at)
                done.append("rescheduled")

    booking.refresh_from_db()
    live_order = order and not order.get("deleted") and order.get("posted")
    if order_changed and live_order and booking.status in ACTIVE_BOOKING_STATUSES:
        if _order_done(order):
            service_id = None
            if not booking.items.exists():
                service_id = _service_from_lines(booking, order.get("lines") or [])
            total = Decimal(order.get("total") or 0)
            booking_service.complete(
                user,
                booking.pk,
                final_price=total if total > 0 else None,
                reason=f"Итог по заказ-наряду {sync.order_number} в 1С",
                service_id=service_id,
            )
            done.append("completed")
        elif booking.status == BookingStatus.PENDING:
            booking_service.start_work(user, booking.pk)
            done.append("started")

    sync.request_version = (request.get("version") or sync.request_version)[:64]
    sync.order_version = (order.get("version") or sync.order_version)[:64]
    _set_error(sync, "")
    sync.save()
    return done


def apply_changes(user: User, items: list[dict]) -> list[dict]:
    """Правки из 1С — каждая запись своей транзакцией.

    Одна неудачная запись не должна откатить остальные: 1С прислала
    пачку, и чек, пробитый по соседнему заказ-наряду, обязан доехать.
    """
    results = []
    for item in items:
        try:
            with transaction.atomic():
                applied = _apply_one(user, item)
            results.append({"id": str(item["id"]), "ok": True, "applied": applied})
        except DomainError as exc:
            _remember_failure(user, item, exc)
            results.append({"id": str(item["id"]), "ok": False, "error": exc.to_dict()})
    return results


@transaction.atomic
def _remember_failure(user: User, item: dict, exc: DomainError) -> None:
    """Правку не приняли — вернуть в 1С состояние сайта и запомнить почему.

    Версии из 1С запоминаем: та же заявка в следующем обмене — уже не
    новая правка, а та, что не прошла; повторять её каждую минуту незачем.
    """
    booking = _visible(user).filter(pk=item["id"]).first()
    if booking is None:
        return
    sync = _sync_for(booking)
    sync.exported_version = None
    request = item.get("request") or {}
    order = item.get("order") or {}
    sync.request_version = (request.get("version") or sync.request_version)[:64]
    sync.order_version = (order.get("version") or sync.order_version)[:64]
    _set_error(sync, exc.message)
    sync.save()
    logger.info("Правка из 1С по записи %s не принята: %s", booking.code, exc.code)
