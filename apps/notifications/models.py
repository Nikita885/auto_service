from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class NotificationKind(models.TextChoices):
    OTP = "otp", "Код входа"
    BOOKING_CREATED = "booking_created", "Запись создана"
    BOOKING_REMINDER = "booking_reminder", "Напоминание о визите"
    BOOKING_CANCELLED_BY_MASTER = "booking_cancelled_by_master", "Отмена сервисом"
    BOOKING_COMPLETED = "booking_completed", "Работы выполнены"


class NotificationChannel(models.TextChoices):
    SMS = "sms", "SMS"
    PUSH = "push", "Push"


class NotificationStatus(models.TextChoices):
    PENDING = "pending", "В очереди"
    SENT = "sent", "Отправлено"
    FAILED = "failed", "Ошибка"


class Notification(BaseModel):
    """Журнал отправленных сообщений.

    Нужен для трёх вещей: доказать, что клиента предупредили об отмене;
    не отправить одно и то же дважды; посчитать расходы на SMS.

    Текст кода входа здесь намеренно замаскирован — сам код в базу
    не попадает.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
        verbose_name="получатель",
    )
    booking = models.ForeignKey(
        "booking.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
        verbose_name="запись",
    )
    phone = models.CharField("телефон", max_length=20)
    channel = models.CharField(
        "канал",
        max_length=10,
        choices=NotificationChannel.choices,
        default=NotificationChannel.SMS,
    )
    kind = models.CharField("тип", max_length=32, choices=NotificationKind.choices)
    text = models.TextField("текст")
    status = models.CharField(
        "статус",
        max_length=10,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
        db_index=True,
    )
    provider_message_id = models.CharField("id у провайдера", max_length=128, blank=True)
    error = models.TextField("ошибка", blank=True)
    sent_at = models.DateTimeField("отправлено", null=True, blank=True)

    class Meta:
        verbose_name = "уведомление"
        verbose_name_plural = "уведомления"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["phone", "-created_at"]),
            models.Index(fields=["kind", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} -> {self.phone} [{self.status}]"
