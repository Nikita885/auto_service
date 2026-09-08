from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.accounts.constants import UserRole
from apps.accounts.managers import UserManager
from apps.common.models import TimeStampedModel, UUIDModel


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    """Пользователь системы: и клиент, и мастер, и админ.

    Логин — телефон в формате E.164. У клиента пароля нет (unusable),
    вход только по одноразовому SMS-коду. У мастера/админа пароль есть,
    чтобы можно было зайти в Django-админку.
    """

    phone = models.CharField("телефон", max_length=20, unique=True, db_index=True)
    full_name = models.CharField("имя", max_length=150, blank=True)
    role = models.CharField(
        "роль", max_length=16, choices=UserRole.choices, default=UserRole.CLIENT
    )

    # Автомобиль клиента: мастеру нужно понимать, что заезжает.
    # Хранится в профиле, а не в шагах записи, чтобы не удлинять сценарий.
    car_model = models.CharField("марка и модель", max_length=120, blank=True)
    car_plate = models.CharField("госномер", max_length=16, blank=True)

    # Точки, к которым привязан мастер. Пусто — значит видит все точки.
    # Клиентов это поле не касается.
    service_points = models.ManyToManyField(
        "catalog.ServicePoint",
        blank=True,
        related_name="masters",
        verbose_name="точки мастера",
        help_text="Пусто = доступ ко всем точкам",
    )

    is_active = models.BooleanField("активен", default=True)
    is_staff = models.BooleanField("доступ в админку", default=False)
    date_joined = models.DateTimeField("дата регистрации", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        indexes = [models.Index(fields=["role", "is_active"])]

    def __str__(self) -> str:
        return f"{self.full_name or 'Без имени'} ({self.phone})"

    @property
    def is_client(self) -> bool:
        return self.role == UserRole.CLIENT

    @property
    def is_master(self) -> bool:
        return self.role in (UserRole.MASTER, UserRole.ADMIN)

    @property
    def display_name(self) -> str:
        return self.full_name or "Клиент"

    def accessible_point_ids(self) -> list | None:
        """id точек, доступных сотруднику. None — доступны все."""
        if self.role == UserRole.ADMIN:
            return None
        ids = list(self.service_points.values_list("id", flat=True))
        return ids or None


class OtpCodeQuerySet(models.QuerySet):
    def active(self):
        return self.filter(used_at__isnull=True, expires_at__gt=timezone.now())

    def for_phone(self, phone: str):
        return self.filter(phone=phone)


class OtpCode(UUIDModel, TimeStampedModel):
    """Одноразовый код для входа по телефону.

    Сам код в базе не хранится — только хеш. Утечка дампа не должна
    давать возможность войти в чужой аккаунт.
    """

    phone = models.CharField("телефон", max_length=20, db_index=True)
    code_hash = models.CharField("хеш кода", max_length=128)
    expires_at = models.DateTimeField("действителен до")
    used_at = models.DateTimeField("использован", null=True, blank=True)
    attempts = models.PositiveSmallIntegerField("попыток ввода", default=0)
    request_ip = models.GenericIPAddressField("IP запроса", null=True, blank=True)

    objects = OtpCodeQuerySet.as_manager()

    class Meta:
        verbose_name = "SMS-код"
        verbose_name_plural = "SMS-коды"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["phone", "-created_at"])]

    def __str__(self) -> str:
        return f"OTP {self.phone} до {self.expires_at:%H:%M:%S}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_used(self) -> bool:
        return self.used_at is not None
