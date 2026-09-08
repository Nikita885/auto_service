"""Нормализация телефона.

Телефон — это логин. Значит `+7 (900) 123-45-67`, `8 900 123 45 67`
и `79001234567` обязаны схлопываться в одну строку, иначе один и тот же
человек заведёт три аккаунта. Приводим всё к E.164: `+79001234567`.
"""

from __future__ import annotations

import phonenumbers
from django.conf import settings

from apps.common.exceptions import ValidationError


def normalize_phone(raw: str, region: str | None = None) -> str:
    region = region or settings.DEFAULT_PHONE_REGION
    value = (raw or "").strip()
    if not value:
        raise ValidationError("Не указан номер телефона", code="phone_required")

    try:
        parsed = phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException as exc:
        raise ValidationError(
            "Не удалось разобрать номер телефона", code="phone_invalid"
        ) from exc

    if not phonenumbers.is_valid_number(parsed):
        raise ValidationError("Некорректный номер телефона", code="phone_invalid")

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def mask_phone(phone: str) -> str:
    """`+79001234567` -> `+7900***4567`. Для логов и списков в панели мастера."""
    if len(phone) < 8:
        return "***"
    return f"{phone[:5]}***{phone[-4:]}"
