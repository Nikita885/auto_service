import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.booking.constants import BookingStatus
from apps.booking.models import Booking, BookingDraft
from apps.booking.services import draft as draft_service

logger = logging.getLogger(__name__)


@shared_task(name="apps.booking.tasks.expire_stale_drafts")
def expire_stale_drafts() -> int:
    """Гасит черновики, у которых вышли 5 минут.

    Не единственная защита от «зависшего» черновика: проверка срока стоит
    и на чтении, и на каждом шаге. Задача нужна, чтобы слот освобождался
    для других клиентов, даже если владелец черновика закрыл приложение.
    """
    count = draft_service.expire_stale_drafts()
    if count:
        logger.info("Погашено черновиков: %s", count)
    return count


@shared_task(name="apps.booking.tasks.send_booking_reminders")
def send_booking_reminders() -> int:
    """Напоминание клиенту незадолго до визита."""
    from apps.notifications.services import notify_booking_reminder

    now = timezone.now()
    until = now + timedelta(minutes=settings.BOOKING["REMINDER_LEAD_MINUTES"])

    bookings = Booking.objects.filter(
        status=BookingStatus.PENDING,
        reminder_sent_at__isnull=True,
        start_at__gt=now,
        start_at__lte=until,
    ).select_related("service_point")

    sent = 0
    for booking in bookings:
        # Помечаем до отправки и с проверкой — повторный запуск задачи
        # не должен слать второе SMS.
        claimed = Booking.objects.filter(
            pk=booking.pk, reminder_sent_at__isnull=True
        ).update(reminder_sent_at=now)
        if not claimed:
            continue
        notify_booking_reminder(booking)
        sent += 1

    if sent:
        logger.info("Отправлено напоминаний: %s", sent)
    return sent


@shared_task(name="apps.booking.tasks.purge_old_drafts")
def purge_old_drafts() -> int:
    """Физически удаляет давно закрытые черновики.

    Свежие закрытые оставляем: по ним видно, на каком шаге люди отваливаются.
    """
    threshold = timezone.now() - timedelta(
        days=settings.BOOKING["DRAFT_PURGE_AFTER_DAYS"]
    )
    deleted, _ = BookingDraft.objects.filter(
        is_open=False, booking__isnull=True, created_at__lt=threshold
    ).delete()
    if deleted:
        logger.info("Удалено старых черновиков: %s", deleted)
    return deleted
