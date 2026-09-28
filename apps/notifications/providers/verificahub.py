"""VerificaHub — подтверждение номера обратным звонком, запасное SMS.

Режим входа `OTP_MODE=verificahub`. Отличие от SMS.RU принципиальное:
код знает только шлюз. При обратном звонке кода нет вовсе — клиент сам
звонит на выданный номер (`number_to_call`), шлюз узнаёт его по номеру
звонящего, а мы опрашиваем статус. При SMS код тоже не возвращается:
введённый клиентом код проверяет шлюз (`/v1/verify/check`).

Обратный звонок — исходящий вызов самого клиента: его не глушат ни
антиспам оператора, ни «заглушение неизвестных» на телефоне, на которых
спотыкался входящий звонок с кодом. И он самый дешёвый — 0,25 ₽.

Документация: https://docs.verificahub.ru, спецификация —
https://docs.verificahub.ru/openapi/verificahub-api-v1.json

HTTP — `urllib`, как и у SMS.RU: зависимость ради трёх запросов не нужна.
Ошибки — те же `SmsDeliveryError` (временная, можно повторить) и
`SmsRejectedError` (постоянная: ключ, деньги, номер).
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from apps.notifications.providers.base import SmsDeliveryError, SmsRejectedError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.verificahub.ru"
TIMEOUT_SECONDS = 15

REVERSE_CALL = "reverse_flash_call"
SMS = "sms"

#: Статусы сессии у шлюза.
PENDING = frozenset({"sent", "delivered"})
VERIFIED = "verified"


@dataclass(frozen=True)
class Started:
    request_id: str
    #: Номер, на который клиент звонит сам (только у обратного звонка).
    number_to_call: str | None
    cost: str


@dataclass(frozen=True)
class Status:
    status: str
    failure_reason: str | None = None


class VerificaHubClient:
    """Боевой шлюз."""

    def start(self, phone: str, method: str, expiry_seconds: int) -> Started:
        body = self._request("POST", "/v1/verify", {
            "phone_number": phone,
            "method": method,
            "expiry_seconds": expiry_seconds,
        })
        request_id = body.get("request_id")
        if not request_id:
            raise SmsDeliveryError(f"VerificaHub не вернул request_id: {body}")
        if method == REVERSE_CALL and not body.get("number_to_call"):
            raise SmsDeliveryError(f"VerificaHub не вернул номер для звонка: {body}")
        cost = body.get("cost") or {}
        return Started(
            request_id=str(request_id),
            number_to_call=body.get("number_to_call"),
            cost=f"{cost.get('amount', '?')} {cost.get('currency', '')}".strip(),
        )

    def status(self, request_id: str) -> Status:
        body = self._request("GET", f"/v1/verify/{request_id}")
        return Status(status=str(body.get("status", "")), failure_reason=body.get("failure_reason"))

    def check(self, request_id: str, code: str) -> bool:
        """Проверить код из SMS. False — этим кодом не войти."""
        try:
            body = self._request(
                "POST", "/v1/verify/check", {"request_id": request_id, "code": code}
            )
        except SmsRejectedError as exc:
            # 400 у шлюза — «неверный код» и «сессия истекла» одним кодом;
            # для входа оба значат одно: этим кодом не войти.
            if getattr(exc, "http_status", None) == 400:
                return False
            raise
        return body.get("status") == VERIFIED

    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        conf = settings.VERIFICAHUB
        if not (conf["API_KEY"] and conf["API_SECRET"]):
            raise SmsRejectedError("Не заданы VERIFICAHUB_API_KEY и VERIFICAHUB_API_SECRET")

        token = base64.b64encode(f"{conf['API_KEY']}:{conf['API_SECRET']}".encode()).decode()
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(BASE_URL + path, data=data, method=method)
        request.add_header("Authorization", f"Basic {token}")
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise _problem(exc) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SmsDeliveryError(f"VerificaHub недоступен: {exc!r}") from exc

        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise SmsDeliveryError(f"VerificaHub вернул не JSON: {raw[:200]}") from exc


def _problem(exc: urllib.error.HTTPError) -> Exception:
    """Ошибка шлюза (RFC 7807) → наше исключение.

    4xx — чинить надо настройки, деньги или запрос: повтор не поможет.
    5xx — сбой шлюза, проходит сам.
    """
    try:
        body = json.loads(exc.read().decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        body = {}
    text = f"VerificaHub [{exc.code}] {body.get('title') or ''}: {body.get('detail') or ''}".strip()
    error = SmsDeliveryError(text) if exc.code >= 500 else SmsRejectedError(text)
    error.http_status = exc.code
    return error


class ConsoleVerificaHub:
    """Для разработки: никуда не ходит.

    Номер для звонка — выдуманный; «звонок» считается совершённым на
    втором опросе статуса, чтобы в браузере было видно и ожидание, и вход.
    Код SMS печатается в лог — тем же логгером, что у других заглушек.
    """

    def start(self, phone: str, method: str, expiry_seconds: int) -> Started:
        request_id = f"console-{secrets.token_hex(6)}"
        console = logging.getLogger("apps.notifications.providers.console")
        if method == SMS:
            code = "".join(str(secrets.randbelow(10)) for _ in range(4))
            cache.set(f"vh-console-code:{request_id}", code, expiry_seconds)
            console.warning("[VerificaHub SMS -> %s] код %s", phone, code)
            return Started(request_id=request_id, number_to_call=None, cost="0")
        console.warning("[VerificaHub] %s должен позвонить на +70000000000", phone)
        return Started(request_id=request_id, number_to_call="+70000000000", cost="0")

    def status(self, request_id: str) -> Status:
        polls = cache.get(f"vh-console-polls:{request_id}", 0) + 1
        cache.set(f"vh-console-polls:{request_id}", polls, 600)
        return Status(status=VERIFIED if polls >= 2 else "sent")

    def check(self, request_id: str, code: str) -> bool:
        return cache.get(f"vh-console-code:{request_id}") == code

    @staticmethod
    def console_code(request_id: str) -> str | None:
        """Код SMS заглушки — чтобы вернуть его в ответе API в разработке."""
        return cache.get(f"vh-console-code:{request_id}")


def get_verificahub():
    """Боевой шлюз, а без ключей — заглушка (разработка и тесты).

    На проде заглушку ловит security_audit: без ключей вход не работает.
    """
    conf = settings.VERIFICAHUB
    if conf["API_KEY"] and conf["API_SECRET"]:
        return VerificaHubClient()
    return ConsoleVerificaHub()
