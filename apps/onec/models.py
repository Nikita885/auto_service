from django.db import models

from apps.common.models import BaseModel


class BookingSync(BaseModel):
    """Где запись сайта стоит в 1С и что 1С о ней уже знает.

    Состояние, а не журнал событий: 1С каждый раз получает запись целиком,
    поэтому повтор, потерянный ответ или два обмена подряд ничего не
    ломают — запись просто перезапишется тем же самым. Журнал с курсором
    терял бы события, закоммиченные не по порядку номеров.

    Версии — защита от эха. `exported_version` — `updated_at` записи,
    которую 1С подтвердила: запись правили позже — уйдёт снова.
    `request_version`/`order_version` — `ВерсияДанных` заявки и
    заказ-наряда в 1С, которые сайт уже принял: та же версия при следующем
    обмене значит «в 1С ничего не трогали», и сайт ничего не применяет.
    Без этого заявка, только что переписанная сайтом, вернулась бы как
    правка оператора и откатила бы перенос, сделанный на сайте минутой
    раньше.
    """

    booking = models.OneToOneField(
        "booking.Booking",
        on_delete=models.CASCADE,
        related_name="onec_sync",
        verbose_name="запись",
    )
    exported_version = models.DateTimeField("подтверждённая версия записи", null=True, blank=True)
    exported_at = models.DateTimeField("выгружена в 1С", null=True, blank=True)

    request_number = models.CharField("номер заявки в 1С", max_length=32, blank=True)
    request_version = models.CharField("версия заявки в 1С", max_length=64, blank=True)

    order_ref = models.UUIDField("заказ-наряд в 1С", null=True, blank=True)
    order_number = models.CharField("номер заказ-наряда", max_length=32, blank=True)
    order_state = models.CharField("состояние заказ-наряда", max_length=64, blank=True)
    order_version = models.CharField("версия заказ-наряда", max_length=64, blank=True)
    order_total = models.DecimalField(
        "сумма заказ-наряда", max_digits=10, decimal_places=2, null=True, blank=True
    )
    paid_total = models.DecimalField(
        "оплачено в 1С", max_digits=10, decimal_places=2, null=True, blank=True
    )
    receipt_number = models.CharField("номер чека ККТ", max_length=32, blank=True)
    paid_at = models.DateTimeField("оплачено", null=True, blank=True)

    last_error = models.CharField("последняя ошибка обмена", max_length=500, blank=True)
    error_at = models.DateTimeField("когда ошибка", null=True, blank=True)

    class Meta:
        verbose_name = "запись в 1С"
        verbose_name_plural = "записи в 1С"

    def __str__(self) -> str:
        return f"{self.booking_id} → заявка {self.request_number or '—'}"


class WorkplaceOrder(BaseModel):
    """Снимок обслуживания и устойчивое состояние расчёта рабочего места 1С.

    Проведение бухгалтером не определяет выполнение работ или факт оплаты.
    Неизвестный результат оборудования сохраняется до явной сверки.
    """

    class State(models.TextChoices):
        DRAFT = "draft", "В работе"
        PREPARED = "prepared", "Расчёт подготовлен"
        ACQUIRING = "acquiring", "Ожидается ответ терминала"
        ACQUIRED = "acquired", "Оплата картой подтверждена"
        FISCALIZING = "fiscalizing", "Ожидается ответ ККТ"
        COMPLETED = "completed", "Оплачено, чек получен"
        REVIEW = "review", "Требуется сверка результата"

    booking = models.OneToOneField(
        "booking.Booking", on_delete=models.PROTECT, related_name="workplace_order"
    )
    revision = models.PositiveIntegerField(default=1)
    order_ref = models.UUIDField(null=True, blank=True)
    order_number = models.CharField(max_length=32, blank=True)
    lines = models.JSONField(default=list)
    recommendations = models.TextField(blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    points = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    card = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    state = models.CharField(max_length=16, choices=State.choices, default=State.DRAFT)
    checkout_id = models.UUIDField(null=True, blank=True, unique=True)
    bank_reference = models.CharField(max_length=128, blank=True)
    receipt = models.JSONField(default=dict)
    events = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(total__gte=0), name="onec_total_nonnegative"),
            models.CheckConstraint(
                condition=models.Q(points__gte=0), name="onec_points_nonnegative"
            ),
            models.CheckConstraint(condition=models.Q(cash__gte=0), name="onec_cash_nonnegative"),
            models.CheckConstraint(condition=models.Q(card__gte=0), name="onec_card_nonnegative"),
        ]
