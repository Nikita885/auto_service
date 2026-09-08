import logging

from celery import shared_task
from django.utils import timezone

from apps.notifications.models import Notification, NotificationStatus
from apps.notifications.providers import SmsDeliveryError, get_sms_provider

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="apps.notifications.tasks.deliver_sms",
    autoretry_for=(SmsDeliveryError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def deliver_sms(self, notification_id: str, phone: str, text: str) -> str:
    """Отдать SMS провайдеру.

    Текст приходит параметром, а не берётся из журнала: у кода входа
    в базе лежит маскированная версия.
    """
    provider = get_sms_provider()

    try:
        message_id = provider.send(phone, text)
    except SmsDeliveryError as exc:
        Notification.objects.filter(pk=notification_id).update(
            status=NotificationStatus.FAILED, error=str(exc)
        )
        logger.warning("SMS на %s не доставлено: %s", phone, exc)
        raise
    except Exception as exc:  # непредвиденная ошибка — не ретраим вслепую
        Notification.objects.filter(pk=notification_id).update(
            status=NotificationStatus.FAILED, error=repr(exc)
        )
        logger.exception("Сбой отправки SMS на %s", phone)
        raise

    Notification.objects.filter(pk=notification_id).update(
        status=NotificationStatus.SENT,
        provider_message_id=message_id,
        sent_at=timezone.now(),
        error="",
    )
    return message_id
