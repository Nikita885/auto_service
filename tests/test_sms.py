"""Боевой SMS-шлюз: разбор ответов и экономия на отправках."""

from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from apps.notifications.models import Notification, NotificationKind, NotificationStatus
from apps.notifications.providers import SmsDeliveryError, SmsRejectedError
from apps.notifications.providers.smsru import SmsRuProvider
from apps.notifications.services import send_otp_sms

PHONE = "+79001112233"


@pytest.fixture
def provider(settings):
    settings.SMS = {**settings.SMS, "API_KEY": "test-key", "SENDER": ""}
    return SmsRuProvider()


def _ok_response(sms_id: str = "000000-10000000") -> dict:
    return {
        "status": "OK",
        "status_code": 100,
        "sms": {PHONE.lstrip("+"): {"status": "OK", "status_code": 100, "sms_id": sms_id}},
        "balance": 512.5,
    }


# ------------------------------------------------------------- разбор ответа


def test_successful_send_returns_message_id(provider, monkeypatch):
    monkeypatch.setattr(provider, "_post", lambda payload: _ok_response("abc-1"))
    assert provider.send(PHONE, "Код: 1234") == "abc-1"


def test_sender_name_is_omitted_when_not_agreed(provider, monkeypatch):
    """Пустое имя отправителя не передаём вовсе — иначе шлюз вернёт 204."""
    captured: dict = {}

    def _post(payload):
        captured.update(payload)
        return _ok_response()

    monkeypatch.setattr(provider, "_post", _post)
    provider.send(PHONE, "текст")

    assert "from" not in captured
    assert captured["to"] == "79001112233"  # без плюса, как ждёт шлюз


def test_sender_name_is_passed_when_set(provider, settings, monkeypatch):
    settings.SMS = {**settings.SMS, "SENDER": "AutoService"}
    captured: dict = {}

    def _post(payload):
        captured.update(payload)
        return _ok_response()

    monkeypatch.setattr(provider, "_post", _post)
    provider.send(PHONE, "текст")

    assert captured["from"] == "AutoService"


@pytest.mark.parametrize(
    ("code", "fragment"),
    [
        (200, "неверный api_id"),
        (201, "недостаточно средств"),
        (204, "имя отправителя"),
        (207, "нельзя отправлять"),
    ],
)
def test_permanent_errors_are_not_retried(provider, monkeypatch, code, fragment):
    """Такое не лечится повтором — задача должна остановиться, а не крутиться."""
    monkeypatch.setattr(
        provider,
        "_post",
        lambda payload: {"status": "ERROR", "status_code": code, "status_text": "х"},
    )
    with pytest.raises(SmsRejectedError) as exc:
        provider.send(PHONE, "текст")
    assert fragment in str(exc.value)


def test_unknown_error_code_is_retried(provider, monkeypatch):
    monkeypatch.setattr(
        provider,
        "_post",
        lambda payload: {"status": "ERROR", "status_code": 999, "status_text": "сбой"},
    )
    with pytest.raises(SmsDeliveryError):
        provider.send(PHONE, "текст")


def test_per_number_error_is_caught(provider, monkeypatch):
    """Неверный ключ виден в общем статусе, плохой номер — только во вложенном."""
    body = {
        "status": "OK",
        "status_code": 100,
        "sms": {PHONE.lstrip("+"): {"status": "ERROR", "status_code": 207, "status_text": ""}},
    }
    monkeypatch.setattr(provider, "_post", lambda payload: body)
    with pytest.raises(SmsRejectedError):
        provider.send(PHONE, "текст")


def test_missing_api_key_is_rejected_without_network(settings):
    settings.SMS = {**settings.SMS, "API_KEY": ""}
    with pytest.raises(SmsRejectedError):
        SmsRuProvider().send(PHONE, "текст")


def test_response_without_sms_id_is_an_error(provider, monkeypatch):
    monkeypatch.setattr(
        provider, "_post", lambda payload: {"status": "OK", "status_code": 100, "sms": {}}
    )
    with pytest.raises(SmsDeliveryError):
        provider.send(PHONE, "текст")


# ------------------------------------------------------------- сетевой слой


def test_network_failure_is_retriable(provider, monkeypatch):
    def _boom(request, timeout=None):
        raise URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(SmsDeliveryError):
        provider.send(PHONE, "текст")


def test_http_error_is_retriable(provider, monkeypatch):
    def _boom(request, timeout=None):
        raise HTTPError("https://sms.ru", 502, "Bad Gateway", {}, BytesIO(b""))

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    with pytest.raises(SmsDeliveryError):
        provider.send(PHONE, "текст")


def test_non_json_answer_is_retriable(provider, monkeypatch):
    class _Response:
        def read(self):
            return b"<html>503</html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=None: _Response())
    with pytest.raises(SmsDeliveryError):
        provider.send(PHONE, "текст")


def test_request_is_formed_as_post_with_urlencoded_body(provider, monkeypatch):
    seen: dict = {}

    class _Response:
        def read(self):
            return json.dumps(_ok_response()).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _urlopen(request, timeout=None):
        seen["method"] = request.method
        seen["url"] = request.full_url
        seen["body"] = request.data.decode()
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    provider.send(PHONE, "Код: 1234")

    assert seen["method"] == "POST"
    assert seen["url"] == "https://sms.ru/sms/send"
    assert "api_id=test-key" in seen["body"]
    assert "json=1" in seen["body"]


# ------------------------------------------------------------- экономия


@pytest.mark.django_db
def test_disabled_kind_is_logged_but_not_sent(settings):
    """Выключённый тип остаётся в журнале со статусом «не отправляли».

    Тихо выбрасывать запись нельзя: «клиенту не сообщили» — такой же факт,
    как «сообщили», и он должен быть виден в журнале.
    """
    settings.SMS = {**settings.SMS, "ENABLED_KINDS": ["booking_cancelled_by_master"]}

    notification = send_otp_sms(phone=PHONE, code="1234")

    assert notification.status == NotificationStatus.SKIPPED
    notification.refresh_from_db()
    assert notification.status == NotificationStatus.SKIPPED


@pytest.mark.django_db
def test_enabled_kind_goes_to_the_queue(settings):
    settings.SMS = {**settings.SMS, "ENABLED_KINDS": ["otp"]}

    notification = send_otp_sms(phone=PHONE, code="1234")

    assert notification.status == NotificationStatus.PENDING


@pytest.mark.django_db
def test_otp_code_never_reaches_the_journal(settings):
    """В базе лежит маскированный текст: дамп не должен давать вход в аккаунт."""
    settings.SMS = {**settings.SMS, "ENABLED_KINDS": ["otp"]}

    send_otp_sms(phone=PHONE, code="4321")

    stored = Notification.objects.get(kind=NotificationKind.OTP)
    assert "4321" not in stored.text
