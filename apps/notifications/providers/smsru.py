"""Боевой шлюз SMS.RU.

Выбран из российских шлюзов по трём причинам: регистрация без договора и
без документов, ключ виден в личном кабинете сразу, а на счёт при
регистрации кладут небольшой баланс — его хватает, чтобы проверить
отправку на своём номере до первого платежа.

Смена шлюза на любой другой — это соседний класс и строка в `.env`:
контракт `SmsProvider` менять не придётся. У SMSC, SMS Aero и P1SMS API
устроены так же — POST с ключом и разбор JSON.

HTTP-клиент — `urllib` из стандартной библиотеки, а не `requests`: весь
вызов это один POST, и тащить зависимость в образ ради него значит платить
пересборкой и обновлениями за двадцать строк кода.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from apps.notifications.providers.base import (
    SmsDeliveryError,
    SmsProvider,
    SmsRejectedError,
)

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15

# Коды, которые не исправит повтор: чинить нужно настройки или номер.
# Полный список — https://sms.ru/api/status
PERMANENT_CODES = {
    200: "неверный api_id",
    201: "недостаточно средств на счету",
    202: "неправильно указан получатель",
    203: "нет текста сообщения",
    204: "имя отправителя не согласовано с администрацией",
    205: "сообщение слишком длинное",
    206: "превышен дневной лимит сообщений",
    207: "на этот номер нельзя отправлять сообщения",
    209: "номер в чёрном списке",
    210: "используется GET, требуется POST",
    211: "метод не найден",
    220: "сервис временно недоступен",
    230: "превышен лимит сообщений на этот номер",
    231: "превышен лимит одинаковых сообщений на этот номер",
    232: "превышен лимит одинаковых сообщений в минуту",
}

# 201 «нет денег» формально постоянная, но лечится пополнением счёта —
# повторять её в течение десяти минут смысла всё равно нет.


class SmsRuProvider(SmsProvider):
    endpoint = "https://sms.ru/sms/send"

    def send(self, phone: str, text: str) -> str:
        api_id = settings.SMS["API_KEY"]
        if not api_id:
            raise SmsRejectedError("Не задан SMS_API_KEY")

        payload = {
            # Шлюз ждёт номер без плюса: 79001234567.
            "to": phone.lstrip("+"),
            "msg": text,
            "api_id": api_id,
            "json": 1,
        }
        # Имя отправителя нужно согласовывать отдельно. Пока его нет,
        # параметр не передаём вовсе — иначе шлюз ответит кодом 204.
        sender = settings.SMS["SENDER"]
        if sender:
            payload["from"] = sender

        body = self._post(payload)
        return self._extract_message_id(body, phone)

    # ------------------------------------------------------------------

    def _post(self, payload: dict) -> dict:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(self.endpoint, data=data, method="POST")

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # HTTP-ошибка шлюза — почти всегда его собственный сбой,
            # который проходит сам. Повторяем.
            raise SmsDeliveryError(f"SMS.RU: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SmsDeliveryError(f"SMS.RU недоступен: {exc!r}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SmsDeliveryError(f"SMS.RU вернул не JSON: {raw[:200]}") from exc

    def _extract_message_id(self, body: dict, phone: str) -> str:
        """Разобрать ответ и достать id сообщения.

        У SMS.RU два уровня статусов: общий на запрос и отдельный на каждый
        номер. Неверный ключ виден в общем, недоступный номер — только во
        вложенном, поэтому проверять нужно оба.
        """
        self._raise_for_status(body.get("status_code"), body.get("status_text", ""))

        per_number = (body.get("sms") or {}).get(phone.lstrip("+"), {})
        self._raise_for_status(
            per_number.get("status_code"), per_number.get("status_text", "")
        )

        message_id = per_number.get("sms_id")
        if not message_id:
            raise SmsDeliveryError(f"SMS.RU не вернул sms_id: {body}")

        balance = body.get("balance")
        if balance is not None:
            # Баланс приходит в каждом ответе — бесплатный способ узнать,
            # что деньги кончаются, до того как отправка встанет.
            logger.info("SMS.RU: остаток на счету %s", balance)

        return str(message_id)

    @staticmethod
    def _raise_for_status(code: int | None, text: str) -> None:
        if code is None or code == 100:
            return
        reason = PERMANENT_CODES.get(code)
        if reason:
            raise SmsRejectedError(f"SMS.RU [{code}] {reason}. {text}".strip())
        raise SmsDeliveryError(f"SMS.RU [{code}] {text}".strip())
