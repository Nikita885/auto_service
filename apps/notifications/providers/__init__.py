from __future__ import annotations

from functools import lru_cache

from django.conf import settings

from apps.notifications.providers.base import (
    SmsDeliveryError,
    SmsProvider,
    SmsRejectedError,
)
from apps.notifications.providers.console import ConsoleSmsProvider
from apps.notifications.providers.http_gateway import HttpGatewaySmsProvider
from apps.notifications.providers.smsru import SmsRuProvider

PROVIDERS: dict[str, type[SmsProvider]] = {
    "console": ConsoleSmsProvider,
    "smsru": SmsRuProvider,
    "http": HttpGatewaySmsProvider,
}


@lru_cache(maxsize=1)
def get_sms_provider() -> SmsProvider:
    name = settings.SMS["PROVIDER"]
    try:
        return PROVIDERS[name]()
    except KeyError as exc:
        raise RuntimeError(
            f"Неизвестный SMS-провайдер: {name}. Доступны: {', '.join(PROVIDERS)}"
        ) from exc


__all__ = [
    "SmsProvider",
    "SmsDeliveryError",
    "SmsRejectedError",
    "get_sms_provider",
    "PROVIDERS",
]
