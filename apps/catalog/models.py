from __future__ import annotations

import zoneinfo
from datetime import date, datetime, time

from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import BaseModel


class OilType(models.TextChoices):
    SYNTHETIC = "synthetic", "Синтетическое"
    SEMI_SYNTHETIC = "semi_synthetic", "Полусинтетическое"
    MINERAL = "mineral", "Минеральное"


class ServicePoint(BaseModel):
    """Точка обслуживания (адрес). Сейчас их две, но модель это не ограничивает.

    График и пропускная способность лежат прямо здесь: расписание слотов
    считается на лету из этих полей, отдельной таблицы слотов нет —
    иначе пришлось бы генерировать её вперёд и чистить.
    """

    name = models.CharField("название", max_length=120)
    address = models.CharField("адрес", max_length=255)
    phone = models.CharField("телефон", max_length=20, blank=True)
    latitude = models.DecimalField(
        "широта", max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        "долгота", max_digits=9, decimal_places=6, null=True, blank=True
    )

    timezone = models.CharField("часовой пояс", max_length=64, default="Europe/Moscow")
    opens_at = models.TimeField("открытие", default=time(9, 0))
    closes_at = models.TimeField("закрытие", default=time(21, 0))
    workdays = models.JSONField(
        "рабочие дни",
        default=list,
        help_text="Дни недели, 0 = понедельник. Пустой список = работает всегда.",
    )
    slot_minutes = models.PositiveSmallIntegerField(
        "длительность слота, мин",
        default=30,
        validators=[MinValueValidator(5)],
    )
    posts_count = models.PositiveSmallIntegerField(
        "постов",
        default=2,
        validators=[MinValueValidator(1)],
        help_text="Сколько машин обслуживается одновременно — ёмкость одного слота.",
    )

    is_active = models.BooleanField("активна", default=True)

    class Meta:
        verbose_name = "точка обслуживания"
        verbose_name_plural = "точки обслуживания"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} — {self.address}"

    @property
    def tz(self) -> zoneinfo.ZoneInfo:
        return zoneinfo.ZoneInfo(self.timezone)

    def is_workday(self, day: date) -> bool:
        if not self.workdays:
            return True
        return day.weekday() in self.workdays

    def local_datetime(self, day: date, moment: time) -> datetime:
        """Локальное aware-время точки для указанных даты и времени."""
        return datetime.combine(day, moment, tzinfo=self.tz)


class Oil(BaseModel):
    """Позиция масла. Цена и объём фиксируются в записи на момент брони."""

    brand = models.CharField("бренд", max_length=80)
    name = models.CharField("название", max_length=120)
    viscosity = models.CharField("вязкость", max_length=16, help_text="Например, 5W-30")
    oil_type = models.CharField(
        "тип", max_length=20, choices=OilType.choices, default=OilType.SYNTHETIC
    )
    volume_liters = models.DecimalField(
        "объём канистры, л", max_digits=4, decimal_places=1, default=4
    )
    price = models.DecimalField("цена за канистру, ₽", max_digits=10, decimal_places=2)
    work_price = models.DecimalField(
        "стоимость работ, ₽", max_digits=10, decimal_places=2, default=0
    )
    description = models.TextField("описание", blank=True)
    is_active = models.BooleanField("в продаже", default=True)

    class Meta:
        verbose_name = "масло"
        verbose_name_plural = "масла"
        ordering = ["brand", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "name", "viscosity", "volume_liters"],
                name="uniq_oil_sku",
            )
        ]

    def __str__(self) -> str:
        return f"{self.brand} {self.name} {self.viscosity}, {self.volume_liters} л"

    @property
    def total_price(self):
        return self.price + self.work_price


class OilStock(BaseModel):
    """Остаток масла на конкретной точке.

    `quantity` — физический остаток в канистрах. Записи его не уменьшают:
    доступность считается как остаток минус активные брони и черновики.
    Списание происходит один раз, при завершении работ.
    """

    service_point = models.ForeignKey(
        ServicePoint, on_delete=models.CASCADE, related_name="stocks",
        verbose_name="точка",
    )
    oil = models.ForeignKey(
        Oil, on_delete=models.CASCADE, related_name="stocks", verbose_name="масло"
    )
    quantity = models.PositiveIntegerField("остаток, канистр", default=0)

    class Meta:
        verbose_name = "остаток масла"
        verbose_name_plural = "остатки масла"
        constraints = [
            models.UniqueConstraint(
                fields=["service_point", "oil"], name="uniq_stock_per_point"
            )
        ]
        indexes = [models.Index(fields=["service_point", "oil"])]

    def __str__(self) -> str:
        return f"{self.oil} @ {self.service_point.name}: {self.quantity} шт."
