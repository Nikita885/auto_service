import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.accounts.models import OtpCode

logger = logging.getLogger(__name__)


@shared_task(name="apps.accounts.tasks.purge_expired_otp")
def purge_expired_otp() -> int:
    """Использованные и протухшие коды больше суток не нужны никому."""
    threshold = timezone.now() - timedelta(days=1)
    deleted, _ = OtpCode.objects.filter(created_at__lt=threshold).delete()
    if deleted:
        logger.info("Удалено просроченных OTP: %s", deleted)
    return deleted
