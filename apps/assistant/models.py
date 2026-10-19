from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class AssistantRequest(BaseModel):
    """Одно сообщение клиента подсказчику — счётчик, а не переписка.

    Текст разговора не храним (решение заказчика): ни вопроса, ни ответа.
    Остаётся то, без чего не работают лимиты и потолок трат, — кто, когда,
    в каком разговоре, сколько токенов и рублей, — и что подсказчик
    предложил: по этому видно, помогает ли он выбирать.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_requests",
        verbose_name="клиент",
    )
    service_point = models.ForeignKey(
        "catalog.ServicePoint",
        on_delete=models.SET_NULL,
        null=True,
        related_name="assistant_requests",
        verbose_name="точка",
    )
    # Разговор — несколько сообщений подряд; лимит на разговор считается по нему.
    chat = models.UUIDField("разговор", db_index=True)
    provider = models.CharField("провайдер", max_length=20)
    model = models.CharField("модель", max_length=120, blank=True)
    input_tokens = models.PositiveIntegerField("токенов на входе", default=0)
    output_tokens = models.PositiveIntegerField("токенов на выходе", default=0)
    cost = models.DecimalField("стоимость, ₽", max_digits=10, decimal_places=4, default=0)
    # Что предложил: категорию, услугу или «подберём на месте» в категории.
    category = models.ForeignKey(
        "catalog.ServiceCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="предложенная категория",
    )
    service = models.ForeignKey(
        "catalog.Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="предложенная услуга",
    )
    on_site = models.BooleanField("предложил «подберём на месте»", default=False)
    # Пусто — ответ получен. Иначе — почему нет: провайдер не ответил и т. п.
    # Неудачные запросы в лимиты клиента не идут.
    error = models.CharField("ошибка", max_length=40, blank=True)

    class Meta:
        verbose_name = "сообщение подсказчику"
        verbose_name_plural = "подсказчик: сообщения"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "created_at"])]

    def __str__(self) -> str:
        return f"{self.created_at:%d.%m %H:%M} · {self.cost} ₽"
