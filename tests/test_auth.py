"""Вход по номеру телефона без пароля."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.models import OtpCode, User

pytestmark = pytest.mark.django_db


def request_otp(api, phone: str):
    return api.post(reverse("v1:accounts:otp-request"), {"phone": phone}, format="json")


def verify_otp(api, phone: str, code: str):
    return api.post(
        reverse("v1:accounts:otp-verify"), {"phone": phone, "code": code}, format="json"
    )


def get_code(api, phone: str) -> str:
    """В тестовых настройках код возвращается в ответе — SMS-шлюз не нужен."""
    response = request_otp(api, phone)
    assert response.status_code == 200, response.data
    return response.data["debug_code"]


def test_new_phone_creates_account(api):
    code = get_code(api, "+7 900 111-22-33")
    response = verify_otp(api, "+79001112233", code)

    assert response.status_code == 200
    assert response.data["is_new_user"] is True
    assert response.data["access"]
    assert User.objects.filter(phone="+79001112233").exists()


def test_code_is_not_stored_in_plain_text(api):
    code = get_code(api, "+79001112233")
    otp = OtpCode.objects.get()

    assert code not in otp.code_hash
    assert len(otp.code_hash) > 20


def test_phone_is_normalized(api):
    """8-ка, +7 и пробелы — это один человек, а не три аккаунта."""
    verify_otp(api, "+79001112233", get_code(api, "8 (900) 111-22-33"))

    OtpCode.objects.all().delete()
    verify_otp(api, "89001112233", get_code(api, "+7 900 111 22 33"))

    assert User.objects.count() == 1


def test_wrong_code_is_rejected_and_counted(api):
    get_code(api, "+79001112233")

    response = verify_otp(api, "+79001112233", "9999")

    assert response.status_code == 400
    assert response.data["error"]["code"] == "otp_invalid"
    assert OtpCode.objects.get().attempts == 1


def test_attempts_are_limited(api, settings):
    settings.OTP = {**settings.OTP, "MAX_VERIFY_ATTEMPTS": 2}
    real_code = get_code(api, "+79001112233")

    verify_otp(api, "+79001112233", "0001")
    verify_otp(api, "+79001112233", "0002")
    blocked = verify_otp(api, "+79001112233", real_code)

    assert blocked.status_code == 429
    assert blocked.data["error"]["code"] == "otp_attempts_exceeded"


def test_resend_is_throttled_by_cooldown(api):
    get_code(api, "+79001112233")
    second = request_otp(api, "+79001112233")

    assert second.status_code == 429
    assert second.data["error"]["code"] == "otp_cooldown"
    assert "retry_after" in second.data["error"]["details"]


def test_code_is_single_use(api):
    code = get_code(api, "+79001112233")

    assert verify_otp(api, "+79001112233", code).status_code == 200
    assert verify_otp(api, "+79001112233", code).status_code == 400


def test_new_request_invalidates_previous_code(api, settings):
    settings.OTP = {**settings.OTP, "RESEND_COOLDOWN_SECONDS": 0}

    old_code = get_code(api, "+79001112233")
    new_code = get_code(api, "+79001112233")

    assert verify_otp(api, "+79001112233", old_code).status_code == 400
    assert verify_otp(api, "+79001112233", new_code).status_code == 200


def test_invalid_phone_rejected(api):
    response = request_otp(api, "12345")

    assert response.status_code == 400
    assert response.data["error"]["code"] == "phone_invalid"


def test_me_requires_token(api):
    assert api.get(reverse("v1:accounts:me")).status_code == 401


def test_profile_update(auth, client_user):
    api = auth(client_user)

    response = api.patch(
        reverse("v1:accounts:me"),
        {"full_name": "Новое Имя", "car_plate": "О001ОО77", "phone": "+70000000000"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["full_name"] == "Новое Имя"

    client_user.refresh_from_db()
    assert client_user.car_plate == "О001ОО77"
    assert client_user.phone == "+79001112233"  # телефон через профиль не меняется
