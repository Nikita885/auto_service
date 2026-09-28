"""Вход звонком (SMS после неудачных звонков) и вход сотрудников по паролю."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts import services
from apps.accounts.constants import OtpChannel
from apps.accounts.models import OtpCode, User
from apps.common.exceptions import PermissionError_
from apps.common.management.commands import security_audit
from apps.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
)
from apps.notifications.providers import SmsDeliveryError, SmsRejectedError
from apps.notifications.providers import call as call_providers
from apps.notifications.providers.smsru import SmsRuProvider

pytestmark = pytest.mark.django_db(transaction=True)

PHONE = "+79001112233"


def request_code(api, channel=None, phone=PHONE):
    body = {"phone": phone}
    if channel:
        body["channel"] = channel
    return api.post(reverse("v1:accounts:otp-request"), body, format="json")


def verify(api, code, phone=PHONE):
    return api.post(
        reverse("v1:accounts:otp-verify"), {"phone": phone, "code": code}, format="json"
    )


def later(minutes=1, seconds=5):
    """Сдвиг часов за паузу между запросами кода."""
    return freeze_time(timezone.now() + timedelta(minutes=minutes, seconds=seconds))


# ------------------------------------------------------------ звонок
def test_code_comes_by_call_by_default(api):
    resp = request_code(api)

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["channel"] == "call"
    assert body["sms_available"] is False
    otp = OtpCode.objects.get()
    assert otp.channel == OtpChannel.CALL
    # В журнале — звонок, без кода; SMS не уходило.
    note = Notification.objects.get()
    assert (note.channel, note.kind, note.status) == (
        NotificationChannel.CALL, NotificationKind.OTP, NotificationStatus.SENT,
    )
    assert body["debug_code"] not in note.text
    # Код — последние цифры номера звонящего — подходит для входа.
    assert verify(api, body["debug_code"]).status_code == 200


def test_sms_is_not_offered_before_calls_fail(api):
    resp = request_code(api, channel="sms")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "otp_sms_not_available"
    assert resp.json()["error"]["details"]["calls_left"] == 2
    assert not OtpCode.objects.exists()


def test_sms_is_offered_after_two_calls(api):
    first = request_code(api).json()
    assert first["sms_available"] is False

    with later(1):
        second = request_code(api).json()
    assert second["channel"] == "call"
    assert second["sms_available"] is True  # второй звонок — после него можно SMS

    with later(2, 10):
        third = request_code(api, channel="sms")
    assert third.status_code == 200
    assert third.json()["channel"] == "sms"
    assert OtpCode.objects.order_by("-created_at").first().channel == OtpChannel.SMS
    assert Notification.objects.filter(
        kind=NotificationKind.OTP, channel=NotificationChannel.SMS
    ).exists()


def test_successful_login_resets_call_count(api):
    code = request_code(api).json()["debug_code"]
    with later(1):
        code = request_code(api).json()["debug_code"]
        assert verify(api, code).status_code == 200

    with later(2, 10):
        again = request_code(api).json()
    # После входа звонки считаются заново: SMS снова только после двух.
    assert again["sms_available"] is False


def test_call_failure_falls_back_to_sms(api, monkeypatch):
    class Broken(call_providers.CallCodeProvider):
        def call(self, phone, ip):
            raise SmsRejectedError("SMS.RU [201] недостаточно средств")

    monkeypatch.setattr(call_providers, "get_call_provider", lambda: Broken())

    resp = request_code(api)

    assert resp.status_code == 200
    assert resp.json()["channel"] == "sms"
    assert OtpCode.objects.get().channel == OtpChannel.SMS
    failed = Notification.objects.get(channel=NotificationChannel.CALL)
    assert failed.status == NotificationStatus.FAILED
    assert verify(api, resp.json()["debug_code"]).status_code == 200


def test_hourly_limit_counts_calls_and_sms_together(api, settings):
    settings.OTP = {**settings.OTP, "MAX_PER_PHONE_PER_HOUR": 3}
    request_code(api)
    with later(1):
        request_code(api)
    with later(2, 10):
        request_code(api, channel="sms")
    with later(3, 15):
        resp = request_code(api)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "otp_hourly_limit"


def test_parallel_request_does_not_pay_for_second_call(api):
    """Пока идёт первый запрос (номер под замком), второй звонок не заказывается."""
    from django.core.cache import cache

    cache.add(f"otp-request:{PHONE}", 1, timeout=30)
    resp = request_code(api)

    assert resp.status_code == 429
    assert not OtpCode.objects.exists()
    assert not Notification.objects.exists()


def test_client_ip_goes_to_call_provider(api, monkeypatch):
    seen = {}

    class Spy(call_providers.CallCodeProvider):
        def call(self, phone, ip):
            seen.update(phone=phone, ip=ip)
            return call_providers.PlacedCall(code="4321", call_id="x")

    monkeypatch.setattr(call_providers, "get_call_provider", lambda: Spy())
    request_code(api, phone="8 900 111-22-33")

    assert seen == {"phone": PHONE, "ip": "127.0.0.1"}


# ------------------------------------------------- SMS.RU, метод звонка
@pytest.fixture
def smsru_call(settings):
    settings.SMS = {**settings.SMS, "API_KEY": "test-key"}
    return call_providers.SmsRuCallProvider()


def _fake_post(monkeypatch, response, captured=None):
    def _post(self, payload, endpoint=None):
        if captured is not None:
            captured.update(payload, endpoint=endpoint)
        return response

    monkeypatch.setattr(SmsRuProvider, "_post", _post)


def test_smsru_call_returns_code_from_gateway(smsru_call, monkeypatch):
    captured = {}
    _fake_post(monkeypatch, {
        "status": "OK", "code": "1435", "call_id": "000000-10000000",
        "cost": 0.4, "balance": 4122.56,
    }, captured)

    placed = smsru_call.call(PHONE, None)

    assert placed == call_providers.PlacedCall(code="1435", call_id="000000-10000000")
    assert captured["endpoint"] == "https://sms.ru/code/call"
    assert captured["phone"] == "79001112233"  # без плюса
    assert captured["ip"] == "-1"  # IP неизвестен — как велит документация


def test_smsru_call_error_is_permanent_for_known_codes(smsru_call, monkeypatch):
    _fake_post(monkeypatch, {"status": "ERROR", "status_code": 201, "status_text": "нет денег"})
    with pytest.raises(SmsRejectedError):
        smsru_call.call(PHONE, "1.2.3.4")


def test_smsru_call_without_code_is_a_delivery_error(smsru_call, monkeypatch):
    _fake_post(monkeypatch, {"status": "OK", "call_id": "1"})
    with pytest.raises(SmsDeliveryError):
        smsru_call.call(PHONE, "1.2.3.4")


def test_smsru_call_requires_api_key(settings):
    settings.SMS = {**settings.SMS, "API_KEY": ""}
    with pytest.raises(SmsRejectedError):
        call_providers.SmsRuCallProvider().call(PHONE, None)


# ------------------------------------------------------- сотрудники
@pytest.fixture
def master(db):
    return User.objects.create_master(phone="+79000000009", password="верный-пароль-1")


def staff_login(api, phone, password):
    return api.post(
        reverse("v1:accounts:staff-login"), {"phone": phone, "password": password}, format="json"
    )


def test_staff_cannot_get_code(api, master):
    """Иначе пароль обходился бы звонком на телефон мастера."""
    resp = request_code(api, phone=master.phone)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "staff_use_password"
    assert not Notification.objects.exists()  # и денег за звонок не потратили


def test_staff_cannot_verify_old_code(master):
    OtpCode.objects.create(
        phone=master.phone, code_hash="x", expires_at=timezone.now() + timedelta(minutes=5)
    )
    with pytest.raises(PermissionError_) as err:
        services.verify_otp(master.phone, "1234")
    assert err.value.code == "staff_use_password"


def test_staff_logs_in_with_password(api, master):
    resp = staff_login(api, "8 900 000-00-09", "верный-пароль-1")

    assert resp.status_code == 200, resp.content
    assert resp.json()["user"]["role"] == "master"
    token = resp.json()["access"]
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert api.get(reverse("v1:master:master-booking-list")).status_code == 200


@pytest.mark.parametrize("case", ["wrong_password", "client", "unknown", "inactive"])
def test_staff_login_refusals_look_the_same(api, master, client_user, case):
    phone, password = master.phone, "верный-пароль-1"
    if case == "wrong_password":
        password = "не тот"
    elif case == "client":
        client_user.set_password("верный-пароль-1")
        client_user.save()
        phone = client_user.phone
    elif case == "unknown":
        phone = "+79007654321"
    else:
        User.objects.filter(pk=master.pk).update(is_active=False)

    resp = staff_login(api, phone, password)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_credentials"


def test_staff_phone_is_locked_after_failures(api, master, settings):
    settings.STAFF_LOGIN = {"MAX_FAILURES": 3, "LOCK_MINUTES": 15}
    for _ in range(3):
        staff_login(api, master.phone, "не тот")

    # Даже верный пароль не проходит, пока номер закрыт.
    resp = staff_login(api, master.phone, "верный-пароль-1")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "login_locked"


def test_successful_staff_login_resets_failures(api, master, settings):
    settings.STAFF_LOGIN = {"MAX_FAILURES": 3, "LOCK_MINUTES": 15}
    staff_login(api, master.phone, "не тот")
    staff_login(api, master.phone, "не тот")
    assert staff_login(api, master.phone, "верный-пароль-1").status_code == 200

    staff_login(api, master.phone, "не тот")
    staff_login(api, master.phone, "не тот")
    assert staff_login(api, master.phone, "верный-пароль-1").status_code == 200


# ------------------------------------------------------------- аудит
def test_audit_fails_on_console_call_provider(settings):
    settings.OTP = {**settings.OTP, "CALL_PROVIDER": "console"}
    finding = security_audit._check_calls()
    assert finding.level == security_audit.FAIL
