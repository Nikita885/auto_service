"""Фасад уведомлений.

Бизнес-логика зовёт `notify_*` и не думает ни про Celery, ни про SMS-шлюз.
Отправка всегда асинхронная: подтверждение записи не должно ждать шлюз,
а падение шлюза не должно откатывать бронь.
"""

from __future__ import annotations

import logging

from apps.notifications import templates
from apps.notifications.models import Notification, NotificationKind

logger = logging.getLogger(__name__)


def _enqueue(notification: Notification, text: str) -> None:
    """Поставить отправку в очередь после коммита текущей транзакции."""
    from django.db import transaction

    from apps.notifications.tasks import deliver_sms

    transaction.on_commit(
        lambda: deliver_sms.delay(str(notification.id), notification.phone, text)
    )


def send_otp_sms(*, phone: str, code: str) -> Notification:
    """SMS с кодом входа.

    В журнал пишется маскированный текст: код не должен оседать в базе,
    иначе доступ к дампу равен доступу к любому аккаунту.
    """
    notification = Notification.objects.create(
        phone=phone,
        kind=NotificationKind.OTP,
        text=templates.otp("****"),
    )
    _enqueue(notification, templates.otp(code))
    return notification


def _booking_notification(booking, kind: str, text: str) -> Notification:
    notification = Notification.objects.create(
        user=booking.user,
        booking=booking,
        phone=booking.client_phone,
        kind=kind,
        text=text,
    )
    _enqueue(notification, text)
    return notification


def notify_booking_created(booking) -> Notification:
    return _booking_notification(
        booking, NotificationKind.BOOKING_CREATED, templates.booking_created(booking)
    )


def notify_booking_reminder(booking) -> Notification:
    return _booking_notification(
        booking, NotificationKind.BOOKING_REMINDER, templates.booking_reminder(booking)
    )


def notify_booking_cancelled_by_master(booking) -> Notification:
    """Обязательное уведомление: сервис отменил визит, клиент должен узнать."""
    return _booking_notification(
        booking,
        NotificationKind.BOOKING_CANCELLED_BY_MASTER,
        templates.booking_cancelled_by_master(booking),
    )


def notify_booking_completed(booking) -> Notification:
    return _booking_notification(
        booking,
        NotificationKind.BOOKING_COMPLETED,
        templates.booking_completed(booking),
    )
