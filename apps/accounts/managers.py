from __future__ import annotations

from django.contrib.auth.models import BaseUserManager

from apps.accounts.constants import UserRole


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, phone: str, password: str | None, **extra):
        from apps.common.phone import normalize_phone

        if not phone:
            raise ValueError("Телефон обязателен")

        user = self.model(phone=normalize_phone(phone), **extra)
        if password:
            user.set_password(password)
        else:
            # Клиенты входят только по SMS-коду — пароля у них нет вовсе.
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, phone: str, password: str | None = None, **extra):
        extra.setdefault("role", UserRole.CLIENT)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(phone, password, **extra)

    def create_master(self, phone: str, password: str | None = None, **extra):
        extra.setdefault("role", UserRole.MASTER)
        extra.setdefault("is_staff", True)
        return self._create(phone, password, **extra)

    def create_superuser(self, phone: str, password: str | None = None, **extra):
        extra.setdefault("role", UserRole.ADMIN)
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra.get("is_staff") is not True or extra.get("is_superuser") is not True:
            raise ValueError("Суперпользователь должен иметь is_staff и is_superuser")
        return self._create(phone, password, **extra)
