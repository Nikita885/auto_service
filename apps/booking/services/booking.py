"""Жизненный цикл подтверждённой записи.

Все переходы статусов проходят через один `_transition`: он проверяет
допустимость перехода, пишет историю и рассылает события. Раскидывать
`booking.status = ...` по вьюхам нельзя — тогда историю и уведомления
рано или поздно забудут.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.booking import events
from apps.booking.constants import (
    FINAL_BOOKING_STATUSES,
    BookingStatus,
)
from apps.booking.models import Booking, BookingStatusLog
from apps.booking.services import stock as stock_service
from apps.common.exceptions import ConflictError, NotFoundError, PermissionError_

logger = logging.getLogger(__name__)

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
        return Booking.objects.select_related("service_point", "oil").get(
            pk=booking_id, user=user
        )
    except Booking.DoesNotExist as exc:
        raise NotFoundError("Запись не найдена", code="booking_not_found") from exc


def get_for_master(master, booking_id) -> Booking:
    try:
        booking = Booking.objects.select_related("service_point", "oil", "user").get(
            pk=booking_id
        )
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
        comment=reason,
    )
    logger.info("Запись %s: %s -> %s", booking.code, from_status, to_status)
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


# ------------------------------------------------------------------ мастер
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
def complete(master, booking_id) -> Booking:
    """Работы выполнены: фиксируем статус и списываем канистру со склада."""
    booking = Booking.objects.select_for_update().get(
        pk=get_for_master(master, booking_id).pk
    )
    _transition(
        booking,
        BookingStatus.COMPLETED,
        actor=master,
        extra_fields={"master": booking.master or master},
    )
    stock_service.write_off(booking)

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
