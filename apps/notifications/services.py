"""Фасад уведомлений.

Бизнес-логика зовёт `notify_*` и не думает ни про Celery, ни про SMS-шлюз.
Отправка всегда асинхронная: подтверждение записи не должно ждать шлюз,
а падение шлюза не должно откатывать бронь.
"""

from __future__ import annotations

import logging

from apps.notifications import templates
from apps.notifications.models import (
    Notification,
    NotificationKind,
    NotificationStatus,
)

logger = logging.getLogger(__name__)


def _enqueue(notification: Notification, text: str) -> None:
    """Поставить отправку в очередь после коммита текущей транзакции.

    Если канал для этого типа выключен в `SMS_ENABLED_KINDS`, запись в
    журнале остаётся, но помечается как неотправленная. Тихо удалять её
    нельзя: «клиенту не сообщили» — такой же факт, как «сообщили».
    """
    from django.conf import settings
    from django.db import transaction

    from apps.notifications.tasks import deliver_sms

    if notification.kind not in settings.SMS["ENABLED_KINDS"]:
        Notification.objects.filter(pk=notification.pk).update(
            status=NotificationStatus.SKIPPED
        )
        notification.status = NotificationStatus.SKIPPED
        logger.info(
            "Уведомление %s на %s не отправлено: канал выключен в настройках",
            notification.kind,
            notification.phone,
        )
        return

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
