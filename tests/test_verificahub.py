"""Режим входа OTP_MODE=verificahub: обратный звонок, запасное SMS у шлюза."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.constants import OtpChannel
from apps.accounts.models import OtpCode, User
from apps.common.management.commands import security_audit
from apps.notifications.models import Notification, NotificationChannel, NotificationStatus
from apps.notifications.providers import SmsDeliveryError, SmsRejectedError
from apps.notifications.providers import verificahub as vh

pytestmark = pytest.mark.django_db(transaction=True)

PHONE = "+79001112233"


@pytest.fixture(autouse=True)
def verificahub_mode(settings):
    settings.OTP = {**settings.OTP, "MODE": "verificahub"}
    settings.VERIFICAHUB = {"API_KEY": "", "API_SECRET": ""}  # заглушка


def request_code(api, channel=None, phone=PHONE):
    body = {"phone": phone, **({"channel": channel} if channel else {})}
    return api.post(reverse("v1:accounts:otp-request"), body, format="json")


def call_status(api, session, phone=PHONE):
    return api.post(
        reverse("v1:accounts:otp-call-status"), {"phone": phone, "session": session}, format="json"
    )


def verify(api, code, phone=PHONE):
    return api.post(
        reverse("v1:accounts:otp-verify"), {"phone": phone, "code": code}, format="json"
    )


def later(minutes=1, seconds=5):
    return freeze_time(timezone.now() + timedelta(minutes=minutes, seconds=seconds))


class Gateway:
    """Шлюз с заданными ответами — для сценариев, которых нет у заглушки."""

    def __init__(self, *, start=None, status="sent", reason=None, check=True):
        self._start, self._status, self._reason, self._check = start, status, reason, check
        self.started: list[str] = []

    def start(self, phone, method, expiry_seconds):
        self.started.append(method)
        outcome = self._start(method) if self._start else None
        if isinstance(outcome, Exception):
            raise outcome
        return vh.Started(
            request_id=f"req-{len(self.started)}",
            number_to_call="+79090000000" if method == vh.REVERSE_CALL else None,
            cost="0.25 RUB",
        )

    def status(self, request_id):
        if isinstance(self._status, Exception):
            raise self._status
        return vh.Status(status=self._status, failure_reason=self._reason)

    def check(self, request_id, code):
        return self._check


@pytest.fixture
def gateway(monkeypatch):
    def _install(**kwargs):
        fake = Gateway(**kwargs)
        monkeypatch.setattr(vh, "get_verificahub", lambda: fake)
        return fake

    return _install


# ------------------------------------------------------- обратный звонок
def test_reverse_call_shows_number_and_session(api):
    resp = request_code(api)

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["channel"] == "reverse_call"
    assert body["number_to_call"] == "+70000000000"
    assert body["session"]
    otp = OtpCode.objects.get()
    assert otp.channel == OtpChannel.REVERSE_CALL
    assert otp.provider_request_id
    assert body["session"] not in otp.session_hash  # хранится только хеш
    note = Notification.objects.get()
    assert (note.channel, note.status) == (NotificationChannel.CALL, NotificationStatus.SENT)


def test_status_waits_then_signs_in(api):
    session = request_code(api).json()["session"]

    pending = call_status(api, session)
    assert pending.status_code == 202
    assert pending.json() == {"status": "pending"}

    done = call_status(api, session)
    assert done.status_code == 200, done.content
    assert done.json()["access"]
    assert done.json()["is_new_user"] is True
    assert User.objects.filter(phone=PHONE).exists()
    assert OtpCode.objects.get().used_at is not None


def test_status_requires_the_session(api, gateway):
    """Знать номер мало: без сессии статус чужого звонка не отдаётся."""
    gateway(status="verified")
    request_code(api)

    resp = call_status(api, "угаданная-сессия")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "otp_not_found"
    assert not User.objects.filter(phone=PHONE).exists()


def test_session_is_one_time(api, gateway):
    gateway(status="verified")
    session = request_code(api).json()["session"]
    assert call_status(api, session).status_code == 200

    again = call_status(api, session)
    assert again.status_code == 400


def test_code_is_not_accepted_for_reverse_call(api):
    request_code(api)

    resp = verify(api, "1234")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "otp_call_required"
    assert OtpCode.objects.get().attempts == 0  # попытку не съели


@pytest.mark.parametrize(
    ("status", "http", "code"),
    [("expired", 410, "otp_expired"), ("failed", 400, "otp_call_failed")],
)
def test_finished_session_ends_the_attempt(api, gateway, status, http, code):
    gateway(status=status, reason="no_response")
    session = request_code(api).json()["session"]

    resp = call_status(api, session)

    assert resp.status_code == http
    assert resp.json()["error"]["code"] == code
    # Погашено и у нас: следующий опрос уже не пойдёт в шлюз.
    assert not OtpCode.objects.active().exists()


def test_gateway_outage_while_polling_is_503(api, gateway):
    gateway(status=SmsDeliveryError("VerificaHub недоступен"))
    session = request_code(api).json()["session"]

    resp = call_status(api, session)

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "otp_unavailable"
    assert OtpCode.objects.active().exists()  # сессия жива, можно спросить снова


def test_staff_cannot_poll(api):
    master = User.objects.create_master(phone="+79000000009", password="x" * 12)
    resp = call_status(api, "что-угодно", phone=master.phone)
    assert resp.status_code == 403


# ------------------------------------------------------------- SMS
def test_sms_only_after_two_calls(api):
    assert request_code(api, channel="sms").status_code == 400

    request_code(api)
    with later(1):
        second = request_code(api).json()
    assert second["sms_available"] is True

    with later(2, 10):
        sms = request_code(api, channel="sms")
    assert sms.status_code == 200
    assert sms.json()["channel"] == "sms"
    assert sms.json()["session"] is None
    # Код знает только шлюз — у нас его нет даже хешем.
    otp = OtpCode.objects.order_by("-created_at").first()
    assert otp.provider_request_id

    # Заглушка отдаёт код в debug_code — вход по нему проверяет шлюз.
    assert verify(api, sms.json()["debug_code"]).status_code == 200


def test_wrong_sms_code_counts_attempts(api, gateway, settings):
    settings.OTP = {**settings.OTP, "MAX_VERIFY_ATTEMPTS": 2, "CALLS_BEFORE_SMS": 0}
    gateway(check=False)
    request_code(api, channel="sms")

    first = verify(api, "0000")
    assert first.status_code == 400
    assert first.json()["error"]["details"]["attempts_left"] == 1
    verify(api, "0001")
    blocked = verify(api, "0002")
    assert blocked.status_code == 429


def test_reverse_call_failure_falls_back_to_sms(api, gateway):
    fake = gateway(start=lambda method: (
        SmsRejectedError("VerificaHub [402] нет денег") if method == vh.REVERSE_CALL else None
    ))

    resp = request_code(api)

    assert resp.status_code == 200
    assert resp.json()["channel"] == "sms"
    assert fake.started == [vh.REVERSE_CALL, vh.SMS]
    assert Notification.objects.filter(status=NotificationStatus.FAILED).count() == 1


def test_both_failing_is_503(api, gateway):
    gateway(start=lambda method: SmsDeliveryError("VerificaHub недоступен"))

    resp = request_code(api)

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "otp_unavailable"
    assert not OtpCode.objects.exists()


def test_smsru_mode_is_untouched(api, settings):
    """Режим 1 — как был: SMS.RU звонит, код вводится руками."""
    settings.OTP = {**settings.OTP, "MODE": "smsru"}
    body = request_code(api).json()
    assert body["channel"] == "call"
    assert body["number_to_call"] is None
    assert verify(api, body["debug_code"]).status_code == 200


# --------------------------------------------------- HTTP-клиент шлюза
@pytest.fixture
def client(settings):
    settings.VERIFICAHUB = {"API_KEY": "key", "API_SECRET": "secret"}
    return vh.VerificaHubClient()


def _respond(monkeypatch, *, body=None, http_error=None, captured=None):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout):
        if captured is not None:
            captured["request"] = request
        if http_error:
            raise urllib.error.HTTPError(
                request.full_url, http_error[0], "err", {},
                io.BytesIO(json.dumps(http_error[1]).encode()),
            )
        return Response(json.dumps(body).encode())

    monkeypatch.setattr(vh.urllib.request, "urlopen", urlopen)


def test_client_starts_reverse_call(client, monkeypatch):
    captured = {}
    _respond(monkeypatch, captured=captured, body={
        "request_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "method": "reverse_flash_call",
        "status": "sent", "number_to_call": "+79090000000",
        "cost": {"amount": 0.25, "currency": "RUB"},
    })

    started = client.start(PHONE, vh.REVERSE_CALL, 300)

    assert started.number_to_call == "+79090000000"
    request = captured["request"]
    assert request.full_url == "https://api.verificahub.ru/v1/verify"
    assert request.get_header("Authorization") == "Basic a2V5OnNlY3JldA=="  # key:secret
    assert json.loads(request.data) == {
        "phone_number": PHONE, "method": "reverse_flash_call", "expiry_seconds": 300,
    }


def test_client_no_funds_is_permanent(client, monkeypatch):
    _respond(monkeypatch, http_error=(402, {"title": "Insufficient funds", "status": 402}))
    with pytest.raises(SmsRejectedError, match="402"):
        client.start(PHONE, vh.REVERSE_CALL, 300)


def test_client_server_error_is_temporary(client, monkeypatch):
    _respond(monkeypatch, http_error=(502, {}))
    with pytest.raises(SmsDeliveryError):
        client.status("req")


def test_client_wrong_code_is_false(client, monkeypatch):
    _respond(monkeypatch, http_error=(400, {"title": "Invalid code", "status": 400}))
    assert client.check("req", "0000") is False


def test_client_reads_status(client, monkeypatch):
    _respond(monkeypatch, body={"status": "failed", "failure_reason": "declined"})
    assert client.status("req") == vh.Status(status="failed", failure_reason="declined")


# ------------------------------------------------------------- аудит
def test_audit_fails_without_keys():
    assert security_audit._check_calls().level == security_audit.FAIL


def test_audit_ok_with_keys(settings):
    settings.VERIFICAHUB = {"API_KEY": "k", "API_SECRET": "s"}
    assert security_audit._check_calls().level == security_audit.OK
