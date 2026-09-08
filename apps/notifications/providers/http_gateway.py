"""Заготовка боевого HTTP-шлюза (SMS.RU, SMSC, Twilio — API у всех похожи).

Оставлено намеренно нереализованным: подключать конкретного оператора
имеет смысл, когда появится договор и ключ. Контракт при этом уже
зафиксирован, менять прикладной код не придётся.
"""

from __future__ import annotations

import logging

from django.conf import settings

from apps.notifications.providers.base import SmsDeliveryError, SmsProvider

logger = logging.getLogger(__name__)


class HttpGatewaySmsProvider(SmsProvider):
    endpoint = "https://example-sms-gateway/send"

    def send(self, phone: str, text: str) -> str:
        api_key = settings.SMS["API_KEY"]
        if not api_key:
            raise SmsDeliveryError("Не задан SMS_API_KEY")

        # import requests
        # response = requests.post(
        #     self.endpoint,
        #     json={"api_id": api_key, "to": phone, "msg": text,
        #           "from": settings.SMS["SENDER"]},
        #     timeout=10,
        # )
        # response.raise_for_status()
        # return response.json()["sms_id"]
        raise SmsDeliveryError("HTTP-шлюз не подключён: укажите SMS_PROVIDER=console")
