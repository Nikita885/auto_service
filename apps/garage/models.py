"""Гараж клиента: его автомобили.

Автомобиль — отдельная сущность, а не две строки в профиле: у клиента их
бывает несколько, мастеру нужно знать, какой из них заезжает, а дневнику
водителя — к какой машине относится заправка.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class CarQuerySet(models.QuerySet):
    def active(self):
        """Не удалённые клиентом. Удалённые остаются в базе ради истории."""
        return self.filter(archived_at__isnull=True)


class Car(BaseModel):
    """Автомобиль клиента.

    `title` — свободная строка «марка и модель», а не обязательная ссылка
    на справочник: справочник подсказывает, но полным не бывает, и редкая
    машина не должна мешать записаться. Ссылки на `CarMake`/`CarModel`
    ставятся, когда клиент выбрал подсказку, — пригодятся для подбора
    масла.

    Удаление — мягкое (`archived_at`): на машину ссылаются записи, и дневник
    с годом заправок не должен пропасть от одного случайного нажатия.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cars",
        verbose_name="владелец",
    )
    title = models.CharField("марка и модель", max_length=120, blank=True)
    make = models.ForeignKey(
        "catalog.CarMake",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="марка из справочника",
    )
    model = models.ForeignKey(
        "catalog.CarModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="модель из справочника",
    )
    plate = models.CharField("госномер", max_length=16, blank=True)
    year = models.PositiveSmallIntegerField("год выпуска", null=True, blank=True)
    mileage = models.PositiveIntegerField("пробег, км", null=True, blank=True)
    vin = models.CharField("VIN", max_length=17, blank=True)
    is_primary = models.BooleanField("основной", default=False)
    archived_at = models.DateTimeField("удалён клиентом", null=True, blank=True)

    objects = CarQuerySet.as_manager()

    class Meta:
        verbose_name = "автомобиль клиента"
        verbose_name_plural = "автомобили клиентов"
        ordering = ["-is_primary", "created_at"]
        constraints = [
            # Основной — ровно один среди живых: его подставляет запись,
            # и «какой из двух основных» не должно быть вопросом.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_primary=True, archived_at__isnull=True),
                name="uniq_primary_car_per_user",
            )
        ]
        indexes = [models.Index(fields=["user", "archived_at"])]

    def __str__(self) -> str:
        return " · ".join(part for part in (self.title, self.plate) if part) or "Автомобиль"

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None
