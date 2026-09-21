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


# Показываем 5 символов с начала и 4 с конца. Порог — их сумма плюс один:
# на более коротком номере срезы перекрываются, и «маска» выдала бы все
# цифры разом, да ещё и повторив часть из них. Короткие номера в E.164
# существуют (сервисные, зарубежные), и маскировка не должна зависеть от
# того, что до сих пор встречались только российские одиннадцатизначные.
_MASK_HEAD = 5
_MASK_TAIL = 4
_MASK_MIN_LENGTH = _MASK_HEAD + _MASK_TAIL + 1


def mask_phone(phone: str) -> str:
    """`+79001234567` -> `+7900***4567`. Для логов: телефон — это ПДн."""
    if len(phone) < _MASK_MIN_LENGTH:
        return "***"
    return f"{phone[:_MASK_HEAD]}***{phone[-_MASK_TAIL:]}"
