"""Жизненный цикл подтверждённой записи.

Все переходы статусов проходят через один `_transition`: он проверяет
допустимость перехода, пишет историю и рассылает события. Раскидывать
`booking.status = ...` по вьюхам нельзя — тогда историю и уведомления
рано или поздно забудут.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.booking import events
from apps.booking.constants import (
    FINAL_BOOKING_STATUSES,
    BookingStatus,
)
from apps.booking.models import Booking, BookingItem, BookingPriceChange, BookingStatusLog
from apps.booking.services import slots as slots_service
from apps.booking.services import stock as stock_service
from apps.catalog.models import Service, ServiceCategory, ServicePoint
from apps.common.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionError_,
    ValidationError,
)

logger = logging.getLogger(__name__)

#: Что стоит в записи вместо услуги, пока её не выбрал мастер: так запись
#: читается и в SMS, и в истории, и в панели без отдельной ветки на «пусто».
ON_SITE_TITLE = "Подберём на месте"

#: Разрешённые переходы. Всё, чего здесь нет, — ошибка бизнес-логики.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    BookingStatus.PENDING: {
        BookingStatus.IN_PROGRESS,
        BookingStatus.COMPLETED,
        BookingStatus.CANCELLED_BY_CLIENT,
        BookingStatus.CANCELLED_BY_MASTER,
        BookingStatus.NO_SHOW,
    },
    BookingStatus.IN_PROGRESS: {
        BookingStatus.COMPLETED,
        BookingStatus.CANCELLED_BY_MASTER,
    },
}


def get_for_client(user, booking_id) -> Booking:
    try:
        return Booking.objects.select_related("service_point", "service_category").get(
            pk=booking_id, user=user
        )
    except Booking.DoesNotExist as exc:
        raise NotFoundError("Запись не найдена", code="booking_not_found") from exc


def get_for_master(master, booking_id) -> Booking:
    try:
        booking = Booking.objects.select_related(
            "service_point", "service_category", "user"
        ).get(pk=booking_id)
    except Booking.DoesNotExist as exc:
        raise NotFoundError("Запись не найдена", code="booking_not_found") from exc

    allowed = master.accessible_point_ids()
    if allowed is not None and booking.service_point_id not in allowed:
        raise PermissionError_(
            "Запись относится к другой точке", code="point_not_allowed"
        )
    return booking


def _transition(
    booking: Booking,
    to_status: BookingStatus,
    *,
    actor=None,
    reason: str = "",
    comment_suffix: str = "",
    extra_fields: dict | None = None,
) -> Booking:
    if booking.status in FINAL_BOOKING_STATUSES:
        raise ConflictError(
            "Запись уже завершена, изменить статус нельзя",
            code="booking_final",
            details={"status": booking.status},
        )

    if to_status not in ALLOWED_TRANSITIONS.get(booking.status, set()):
        raise ConflictError(
            "Недопустимый переход статуса",
            code="invalid_transition",
            details={"from": booking.status, "to": to_status},
        )

    from_status = booking.status
    booking.status = to_status
    fields = ["status", "updated_at"]

    for key, value in (extra_fields or {}).items():
        setattr(booking, key, value)
        fields.append(key)

    booking.save(update_fields=fields)
    BookingStatusLog.objects.create(
        booking=booking,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        comment=", ".join(part for part in (reason, comment_suffix) if part),
    )
    logger.info("Запись %s: %s -> %s", booking.code, from_status, to_status)
    return booking


# ------------------------------------------------------------------ создание
def _snapshot(services: list[Service], *, on_site: bool) -> dict:
    """Снимок услуг и цен на момент брони.

    Итог — сумма позиций, материал — сумма их материалов, работа —
    остаток. Снимок нужен потому же, почему он был у масла: прайс
    поменяется, а чек записи поедет не должен.

    Заодно заполняются прежние поля масла. Это не забытый код, а страховка
    на время переезда: пока старые поля не удалены, запись, созданная
    новой версией, обязана читаться и прошлой — если выкатку придётся
    откатить. Ссылку на масло ставим только когда услуга одна и выросла
    из масла; у мойки такой ссылки нет и быть не может.
    """
    total = sum((service.price for service in services), Decimal(0))
    material = sum((service.material_price for service in services), Decimal(0))
    title = ", ".join(service.name for service in services)
    if not title:
        title = ON_SITE_TITLE if on_site else ""
    legacy_oil_id = services[0].oil_id if len(services) == 1 else None
    return {
        "service_title": title[:255],
        "material_price": material,
        "work_price": total - material,
        "total_price": total,
        "oil_id": legacy_oil_id,
        "oil_title": (title or ON_SITE_TITLE)[:255],
        "oil_price": material,
    }


def _create_items(booking: Booking, services: list[Service]) -> None:
    BookingItem.objects.bulk_create(
        [
            BookingItem(
                booking=booking,
                service=service,
                title=service.name,
                category_title=service.category.name,
                price=service.price,
                material_price=service.material_price,
                quantity=1,
            )
            for service in services
        ]
    )


def create_booking(
    *,
    user,
    point,
    category: ServiceCategory | None,
    services: list[Service] | None,
    start_at,
    end_at,
    client_name: str,
    car=None,
    car_model: str,
    car_plate: str,
    comment: str = "",
    actor,
    log_comment: str,
    on_site: bool = False,
) -> Booking:
    """Записать клиента в уже проверенный слот — общий конец обоих путей.

    Клиент приходит сюда из черновика (`draft.confirm`), мастер — из
    записи по звонку (`walk_in.book`). Проверки слота и доступности
    услуг — у вызывающего, под блокировкой точки: здесь только снимок,
    позиции, история и уведомления, чтобы запись из двух мест выглядела
    одинаково.

    `services` пустой при `on_site=True` — услугу подберут на месте:
    цены в снимке нулевые, их поставит `set_service`, когда мастер
    выберет услугу вместе с клиентом.
    """
    services = list(services or [])
    try:
        # Точка заблокирована, но один клиент может записываться на разные
        # точки одновременно — дубль по времени ловит уникальный индекс.
        with transaction.atomic():
            booking = Booking.objects.create(
                user=user,
                service_point=point,
                service_category=category,
                category_title=category.name if category else "",
                service_on_site=on_site,
                car=car,
                start_at=start_at,
                end_at=end_at,
                status=BookingStatus.PENDING,
                client_name=client_name,
                client_phone=user.phone,
                car_model=car_model,
                car_plate=car_plate,
                client_comment=comment or "",
                **_snapshot(services, on_site=on_site),
            )
            _create_items(booking, services)
    except IntegrityError as exc:
        raise ConflictError(
            "У клиента уже есть запись на это время", code="duplicate_booking"
        ) from exc

    BookingStatusLog.objects.create(
        booking=booking,
        from_status="",
        to_status=BookingStatus.PENDING,
        actor=actor,
        comment=log_comment,
    )

    def _after_commit() -> None:
        from apps.notifications.services import notify_booking_created

        events.publish_booking(booking, events.BOOKING_CREATED)
        notify_booking_created(booking)

    transaction.on_commit(_after_commit)
    return booking


# ------------------------------------------------------------------ клиент
@transaction.atomic
def cancel_by_client(user, booking_id, *, reason: str = "") -> Booking:
    booking = Booking.objects.select_for_update().get(
        pk=get_for_client(user, booking_id).pk
    )

    if not booking.is_cancellable_by_client:
        raise ConflictError(
            "Отменить запись уже нельзя — слишком близко к времени визита "
            "или запись не в статусе ожидания",
            code="cancel_deadline_passed",
            details={"status": booking.status},
        )

    _transition(
        booking,
        BookingStatus.CANCELLED_BY_CLIENT,
        actor=user,
        reason=reason,
        extra_fields={
            "cancel_reason": reason,
            "cancelled_at": timezone.now(),
            "cancelled_by": user,
        },
    )

    transaction.on_commit(
        lambda: events.publish_booking(booking, events.BOOKING_CANCELLED)
    )
    return booking


@transaction.atomic
def reschedule_by_client(user, booking_id, start_at) -> Booking:
    """Клиент переносит свою запись на другое время той же точки.

    Можно, пока можно отменить (`is_cancellable_by_client`): перенос — это
    та же отмена старого времени, и пост под клиента к этому моменту уже
    готовят. Новое время проходит все проверки записи (`validate_slot`)
    под той же блокировкой точки, что и подтверждение черновика, — последний
    пост не достанется двоим. Масло остаётся обещанным той же записи, склад
    не трогаем. Статус не меняется, поэтому `_transition` не нужен; в
    историю пишется строка «перенесена», а напоминание будет отправлено
    заново — к новому времени.
    """
    booking = Booking.objects.select_for_update().get(
        pk=get_for_client(user, booking_id).pk
    )
    if not booking.is_cancellable_by_client:
        raise ConflictError(
            "Перенести запись уже нельзя — слишком близко к времени визита "
            "или запись не в статусе ожидания",
            code="reschedule_deadline_passed",
            details={"status": booking.status},
        )

    # Раньше проверки слота: своё же время занято самой записью, и клиент
    # получил бы «время заняли» вместо понятного «вы уже на это время».
    if start_at == booking.start_at:
        raise ValidationError("Запись уже на это время", code="reschedule_same_time")
    point = ServicePoint.objects.select_for_update().get(pk=booking.service_point_id)
    new_start, new_end = slots_service.validate_slot(point, start_at)

    old_local = booking.local_start()
    booking.start_at = new_start
    booking.end_at = new_end
    booking.reminder_sent_at = None
    try:
        # У клиента может быть другая запись на это время (на другой точке):
        # её ловит уникальный индекс, а не предварительный запрос — без гонки.
        with transaction.atomic():
            booking.save(update_fields=["start_at", "end_at", "reminder_sent_at", "updated_at"])
    except IntegrityError as exc:
        raise ConflictError(
            "У вас уже есть запись на это время", code="duplicate_booking"
        ) from exc

    BookingStatusLog.objects.create(
        booking=booking,
        from_status=booking.status,
        to_status=booking.status,
        actor=user,
        comment=f"Перенесена клиентом с {old_local:%d.%m %H:%M} на "
        f"{booking.local_start():%d.%m %H:%M}",
    )
    transaction.on_commit(lambda: events.publish_booking(booking))
    logger.info("Запись %s перенесена клиентом", booking.code)
    return booking


# ------------------------------------------------------------------ мастер
def _require_not_final(booking: Booking, message: str) -> None:
    if booking.status in FINAL_BOOKING_STATUSES:
        raise ConflictError(message, code="booking_final", details={"status": booking.status})


def _apply_services(booking: Booking, services: list[Service], *, actor) -> Booking:
    """Поставить в запись услуги и записать это в историю отдельной строкой."""
    _require_not_final(booking, "Запись уже завершена, изменить услугу нельзя")
    change = _replace_services(booking, services)
    if change:
        BookingStatusLog.objects.create(
            booking=booking,
            from_status=booking.status,
            to_status=booking.status,
            actor=actor,
            comment=change,
        )
    return booking


def _replace_services(booking: Booking, services: list[Service]) -> str | None:
    """Снимок цен и позиции под новые услуги. Вернуть строку для истории,
    или None, если услуги те же.

    Вызывается под блокировкой строки записи. Своя запись держит прежние
    услуги, а не новые, поэтому доступность новой считается как обычно —
    «возвращать» прежнюю не нужно.
    """
    current = [item.service_id for item in booking.items.all()]
    if current == [service.pk for service in services]:
        # Та же услуга: без этого повторное нажатие выглядело бы как
        # «разобрали» — своя же запись держит последнюю единицу.
        return None

    old_title = booking.service_title or booking.oil_title
    booking.items.all().delete()

    category = services[0].category if services else booking.service_category
    fields = _snapshot(services, on_site=False)
    fields["service_category"] = category
    fields["category_title"] = category.name if category else ""
    fields["service_on_site"] = False
    for key, value in fields.items():
        setattr(booking, key, value)
    booking.save(update_fields=[*fields, "updated_at"])
    _create_items(booking, services)
    return f"Услуга: {booking.service_title} (было: {old_title})"


def _service_for_master(booking: Booking, service_id) -> Service:
    """Услуга для записи — с проверкой доступности, кроме своей же.

    Если запись уже стоит на этой услуге, проверять остаток нельзя: её
    последнюю единицу держит сама запись, и повторное нажатие выглядело бы
    как «разобрали».
    """
    current = [item.service for item in booking.items.select_related("service__category")]
    if len(current) == 1 and str(current[0].pk) == str(service_id):
        return current[0]
    return stock_service.get_available_service(booking.service_point, service_id)


@transaction.atomic
def set_service(master, booking_id, service_id) -> Booking:
    """Мастер выбрал услугу: клиент просил подобрать на месте, или услугу
    заменили по согласию клиента. Запись уходит из очереди звонков."""
    booking = Booking.objects.select_for_update().get(
        pk=get_for_master(master, booking_id).pk
    )
    _apply_services(booking, [_service_for_master(booking, service_id)], actor=master)
    transaction.on_commit(lambda: events.publish_booking(booking))
    logger.info("Запись %s: мастер выбрал услугу", booking.code)
    return booking


@transaction.atomic
def set_oil(master, booking_id, oil_id) -> Booking:
    """То же, но по старому API: масло вместо услуги.

    Остаётся рабочим, пока обновляются приложения: масло ищется среди
    услуг точки по ссылке, с которой его перенесли.
    """
    from apps.catalog.services.oils import service_for_oil

    booking = Booking.objects.select_for_update().get(
        pk=get_for_master(master, booking_id).pk
    )
    service = service_for_oil(booking.service_point, oil_id)
    _apply_services(
        booking, [_service_for_master(booking, service.pk)], actor=master
    )
    transaction.on_commit(lambda: events.publish_booking(booking))
    logger.info("Запись %s: мастер выбрал масло (старое API)", booking.code)
    return booking


def _car_title(model: str, plate: str) -> str:
    return " ".join(part for part in (model, plate) if part) or "не указана"


@transaction.atomic
def edit_by_master(
    master,
    booking_id,
    *,
    service_id=None,
    start_at=None,
    car_id=None,
    car_model: str | None = None,
    car_plate: str | None = None,
    comment: str | None = None,
) -> Booking:
    """Мастер поправил запись после звонка: услугу, время, машину, комментарий.

    `None` — поле не трогаем; пустой комментарий — тоже правка («стереть»).
    Всё — одной транзакцией: если новое время заняли, услуга не поменяется
    наполовину. В историю ложится одна строка со всеми изменениями и тем,
    кто их сделал.

    * Услуга — любая доступная на точке, в той же категории или в другой;
      снимок цен и позиции пересчитываются, как в `set_service`.
    * Время — только у записи в ожидании и с теми же проверками слота, что у
      переноса клиентом, кроме запаса до начала (мастер записывает и на
      ближайшее время, `walk_in`). Напоминание уйдёт заново, к новому времени.
    * Машина — одна из машин клиента (`car_id`) или названная мастером
      (`car_model`/`car_plate`): найдём среди машин клиента или добавим.

    Клиенту о правке не пишем — так решил владелец: мастер только что
    договорился с ним по телефону. Приложение клиента обновится по сокету.
    """
    from apps.garage.services import cars as cars_service

    booking = Booking.objects.select_for_update().get(
        pk=get_for_master(master, booking_id).pk
    )
    _require_not_final(booking, "Запись уже завершена, изменить её нельзя")
    car_named = car_model is not None or car_plate is not None
    if all(value is None for value in (service_id, start_at, car_id, comment)) and not car_named:
        raise ValidationError("Нечего менять", code="edit_empty")

    changes: list[str] = []
    fields: set[str] = set()

    if start_at is not None and start_at != booking.start_at:
        if booking.status != BookingStatus.PENDING:
            raise ConflictError(
                "Клиент уже на посту — время не меняется",
                code="booking_not_pending",
                details={"status": booking.status},
            )
        point = ServicePoint.objects.select_for_update().get(pk=booking.service_point_id)
        old_local = booking.local_start()
        booking.start_at, booking.end_at = slots_service.validate_slot(
            point, start_at, walk_in=True
        )
        booking.reminder_sent_at = None
        fields |= {"start_at", "end_at", "reminder_sent_at"}
        changes.append(f"время {old_local:%d.%m %H:%M} → {booking.local_start():%d.%m %H:%M}")

    if service_id is not None:
        change = _replace_services(booking, [_service_for_master(booking, service_id)])
        if change:
            changes.append(change[0].lower() + change[1:])

    if car_id is not None or car_named:
        if car_id is not None:
            car = cars_service.get_car(booking.user, car_id)
        elif (car_model or "").strip() or (car_plate or "").strip():
            car = cars_service.match_or_add(
                booking.user, title=car_model or "", plate=car_plate or ""
            )
        else:
            raise ValidationError("Укажите машину", code="car_required")
        model, plate = cars_service.snapshot(car)
        if (car.pk, model, plate) != (booking.car_id, booking.car_model, booking.car_plate):
            old = _car_title(booking.car_model, booking.car_plate)
            booking.car, booking.car_model, booking.car_plate = car, model, plate
            fields |= {"car", "car_model", "car_plate"}
            changes.append(f"машина: {_car_title(model, plate)} (было: {old})")

    if comment is not None and comment.strip() != booking.client_comment:
        booking.client_comment = comment.strip()
        fields.add("client_comment")
        changes.append("комментарий изменён" if booking.client_comment else "комментарий стёрт")

    if not changes:
        return booking

    try:
        # У клиента может быть другая запись на новое время (на другой
        # точке) — её ловит уникальный индекс, без гонки.
        with transaction.atomic():
            if fields:
                booking.save(update_fields=[*fields, "updated_at"])
    except IntegrityError as exc:
        raise ConflictError(
            "У клиента уже есть запись на это время", code="duplicate_booking"
        ) from exc

    BookingStatusLog.objects.create(
        booking=booking,
        from_status=booking.status,
        to_status=booking.status,
        actor=master,
        comment=("Правка мастером: " + "; ".join(changes))[:500],
    )
    transaction.on_commit(lambda: events.publish_booking(booking))
    logger.info("Запись %s поправлена мастером", booking.code)
    return booking


@transaction.atomic
def cancel_by_master(master, booking_id, *, reason: str) -> Booking:
    """Отмена сервисом. Клиенту обязательно уходит уведомление с причиной."""
    booking = Booking.objects.select_for_update().get(
        pk=get_for_master(master, booking_id).pk
    )

    _transition(
        booking,
        BookingStatus.CANCELLED_BY_MASTER,
        actor=master,
        reason=reason,
        extra_fields={
            "cancel_reason": reason,
            "cancelled_at": timezone.now(),
            "cancelled_by": master,
        },
    )

    def _after_commit() -> None:
        from apps.notifications.services import notify_booking_cancelled_by_master

        events.publish_booking(booking, events.BOOKING_CANCELLED)
        notify_booking_cancelled_by_master(booking)

    transaction.on_commit(_after_commit)
    return booking


@transaction.atomic
def start_work(master, booking_id) -> Booking:
    booking = Booking.objects.select_for_update().get(
        pk=get_for_master(master, booking_id).pk
    )
    _transition(
        booking,
        BookingStatus.IN_PROGRESS,
        actor=master,
        extra_fields={"master": master},
    )
    transaction.on_commit(lambda: events.publish_booking(booking))
    return booking


@transaction.atomic
def complete(
    master,
    booking_id,
    *,
    points: Decimal = Decimal(0),
    final_price: Decimal | None = None,
    reason: str = "",
    service_id=None,
    oil_id=None,
) -> Booking:
    """Работы выполнены: расчёт, статус, остатки и баллы — одной транзакцией.

    `final_price` — итог, если мастер его поправил: добавил работу, долил
    материала или уступил. Ставится первым: потолок оплаты баллами и
    баллы в плечи считаются уже от него. `points` — сколько чека клиент
    решил закрыть баллами (решает клиент, вводит мастер). Правка итога,
    списание баллов, остатков и баллы в плечи вышестоящих либо
    происходят вместе, либо не происходят вовсе: это деньги.
    `oil_id` — тот же выбор по старому API, пока обновляются приложения.
    Импорт рефералки локальный — иначе apps.booking и apps.referral
    замкнулись бы друг на друга, как это уже сделано с уведомлениями.
    """
    from apps.referral.services import points as referral_points
    from apps.referral.services import tree as referral_tree

    booking = Booking.objects.select_for_update().get(
        pk=get_for_master(master, booking_id).pk
    )
    # Статус проверяем до денег: у завершённой записи поменять итог или
    # списать баллы и потом упасть на переходе значило бы откатывать чужой
    # баланс. Сам переход проверит его ещё раз.
    if booking.status in FINAL_BOOKING_STATUSES:
        raise ConflictError(
            "Запись уже завершена, изменить статус нельзя",
            code="booking_final",
            details={"status": booking.status},
        )

    # Услуга ставится первой: от неё цена записи, от цены — потолок
    # баллов. Без услуги выполнить нельзя: нечего посчитать и нечего
    # списать с остатка.
    if service_id or oil_id:
        if oil_id and not service_id:
            from apps.catalog.services.oils import service_for_oil

            service_id = service_for_oil(booking.service_point, oil_id).pk
        _apply_services(
            booking, [_service_for_master(booking, service_id)], actor=master
        )
    elif not booking.items.exists():
        raise ValidationError(
            "Укажите услугу — клиент просил подобрать её на месте",
            code="service_required",
        )

    extra = {"master": booking.master or master}
    notes = []

    old_price = booking.charged_price
    if final_price is not None and Decimal(final_price) != old_price:
        final_price = Decimal(final_price)
        if final_price <= 0:
            raise ValidationError("Итог должен быть больше нуля", code="invalid_price")
        booking.final_price = final_price
        extra["final_price"] = final_price
        notes.append(f"итог {final_price:.2f} вместо {old_price:.2f}")

    points = Decimal(points or 0)
    if points > 0:
        node = referral_tree.get_node(booking.user)
        if node is None:
            raise ConflictError("У клиента нет баллов", code="not_enough_points")
        entry = referral_points.spend(node, points, booking=booking)
        extra["points_spent"] = booking.points_spent - entry.amount
        notes.append(f"баллами {extra['points_spent']}")

    _transition(
        booking,
        BookingStatus.COMPLETED,
        actor=master,
        reason=reason if "final_price" in extra else "",
        comment_suffix=", ".join(notes),
        extra_fields=extra,
    )
    if "final_price" in extra:
        BookingPriceChange.objects.create(
            booking=booking,
            old_price=old_price,
            new_price=booking.final_price,
            reason=reason,
            actor=master,
        )
    stock_service.write_off(booking)
    referral_points.credit_legs_for_booking(booking)

    def _after_commit() -> None:
        from apps.notifications.services import notify_booking_completed

        events.publish_booking(booking)
        notify_booking_completed(booking)

    transaction.on_commit(_after_commit)
    return booking


@transaction.atomic
def mark_no_show(master, booking_id, *, reason: str = "") -> Booking:
    booking = Booking.objects.select_for_update().get(
        pk=get_for_master(master, booking_id).pk
    )
    _transition(booking, BookingStatus.NO_SHOW, actor=master, reason=reason)
    transaction.on_commit(lambda: events.publish_booking(booking))
    return booking
