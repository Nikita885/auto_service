"""Код входа звонком: человеку звонят, код — последние цифры номера.

Отличие от SMS принципиальное: код придумываем не мы, его называет шлюз —
это хвост номера, с которого он позвонит. Поэтому звонок заказывается
синхронно, прямо в запросе кода: без ответа шлюза нечего сохранить и
нечего проверять. Очередь Celery, как у SMS, здесь не подходит.

Звонок дешевле SMS (у SMS.RU — 0,40 ₽ против рубля с лишним) и не требует
согласованного буквенного отправителя: без него SMS не уходят вовсе.
"""

from __future__ import annotations

import abc
import logging
import secrets
from dataclasses import dataclass

from django.conf import settings

from apps.notifications.providers.base import SmsDeliveryError, SmsRejectedError
from apps.notifications.providers.smsru import SmsRuProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlacedCall:
    #: Последние цифры номера, с которого позвонят, — это и есть код.
    code: str
    #: id звонка у шлюза — для журнала и разбора жалоб.
    call_id: str


class CallCodeProvider(abc.ABC):
    @abc.abstractmethod
    def call(self, phone: str, ip: str | None) -> PlacedCall:
        """Заказать звонок. Ошибки — те же `SmsDeliveryError`/`SmsRejectedError`."""
        raise NotImplementedError


class ConsoleCallProvider(CallCodeProvider):
    """Для разработки: никому не звонит, код печатает в лог."""

    def call(self, phone: str, ip: str | None) -> PlacedCall:
        code = "".join(str(secrets.randbelow(10)) for _ in range(4))
        # Логгер тот же, что у SMS-заглушки: он один печатает коды целиком,
        # и на проде его нет (security_audit).
        logging.getLogger("apps.notifications.providers.console").warning(
            "[ЗВОНОК -> %s] код %s", phone, code
        )
        return PlacedCall(code=code, call_id=f"console-{secrets.token_hex(4)}")


class SmsRuCallProvider(CallCodeProvider):
    """SMS.RU, метод /code/call — https://sms.ru/docs/api/api_group_call/code_call

    Ключ тот же, что у SMS (`SMS_API_KEY`), и разбор ошибок тот же: общий
    код статуса SMS.RU. IP клиента шлюз просит для защиты от перебора
    номеров с одного адреса; неизвестный IP — «-1», как в документации.
    """

    endpoint = "https://sms.ru/code/call"

    def call(self, phone: str, ip: str | None) -> PlacedCall:
        api_id = settings.SMS["API_KEY"]
        if not api_id:
            raise SmsRejectedError("Не задан SMS_API_KEY")

        body = SmsRuProvider()._post(
            {"phone": phone.lstrip("+"), "ip": ip or "-1", "api_id": api_id, "json": 1},
            endpoint=self.endpoint,
        )

        if body.get("status") != "OK":
            SmsRuProvider._raise_for_status(body.get("status_code"), body.get("status_text", ""))
            raise SmsDeliveryError(f"SMS.RU: звонок не заказан: {body}")

        code = str(body.get("code") or "")
        if not (code.isdigit() and len(code) == 4):
            raise SmsDeliveryError(f"SMS.RU не вернул код звонка: {body}")

        if body.get("balance") is not None:
            logger.info("SMS.RU: звонок %s ₽, остаток %s", body.get("cost"), body["balance"])
        return PlacedCall(code=code, call_id=str(body.get("call_id") or ""))


CALL_PROVIDERS: dict[str, type[CallCodeProvider]] = {
    "console": ConsoleCallProvider,
    "smsru": SmsRuCallProvider,
}


def get_call_provider() -> CallCodeProvider:
    name = settings.OTP["CALL_PROVIDER"]
    try:
        return CALL_PROVIDERS[name]()
    except KeyError as exc:
        raise RuntimeError(
            f"Неизвестный провайдер звонков: {name}. Доступны: {', '.join(CALL_PROVIDERS)}"
        ) from exc
