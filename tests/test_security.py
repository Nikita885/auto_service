"""Безопасность эксплуатации: кого считаем клиентом, что пишем в лог,
что проверяет аудит перед продом.

Тесты здесь про инфраструктурные решения, а не про бизнес-сценарии. Они
нужны, потому что ошибка в каждом из этих мест не роняет ни один рабочий
сценарий: всё продолжает работать, просто лимит перестаёт лимитировать,
а телефон клиента ложится в лог открытым текстом.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import timedelta

import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from rest_framework.test import APIRequestFactory

from apps.accounts.models import User
from apps.common.management.commands import security_audit
from apps.common.net import client_ip
from apps.common.phone import mask_phone
from apps.common.secret_key import secret_key_problem

REST = {
    "DEFAULT_THROTTLE_RATES": {"otp_request": "10/hour", "otp_verify": "20/hour"},
}


def _request(xff: str | None, remote: str = "10.0.0.7"):
    factory = APIRequestFactory()
    headers = {"REMOTE_ADDR": remote}
    if xff is not None:
        headers["HTTP_X_FORWARDED_FOR"] = xff
    return factory.post("/api/v1/auth/otp/request/", **headers)


# --------------------------------------------------------------- client_ip


@override_settings(REST_FRAMEWORK={**REST, "NUM_PROXIES": 1})
def test_client_ip_behind_one_proxy_takes_last_entry():
    """За одним nginx верить можно только последнему элементу: его дописал
    сам nginx через $proxy_add_x_forwarded_for."""
    request = _request("203.0.113.9, 198.51.100.4")
    assert client_ip(request) == "198.51.100.4"


@override_settings(REST_FRAMEWORK={**REST, "NUM_PROXIES": 1})
def test_client_ip_ignores_headers_invented_by_the_client():
    """Главное свойство: подставив свой X-Forwarded-For, клиент не меняет
    ключ, по которому его считает throttling. Иначе лимит «10 кодов в час
    на IP» обходится одной строкой в запросе — и перебор номеров идёт за
    счёт владельца шлюза."""
    real = _request("198.51.100.4")
    forged = _request("1.2.3.4, 5.6.7.8, 198.51.100.4")
    assert client_ip(real) == client_ip(forged) == "198.51.100.4"


@override_settings(REST_FRAMEWORK={**REST, "NUM_PROXIES": 0})
def test_client_ip_without_proxies_uses_remote_addr():
    """В разработке приложение смотрит в сеть напрямую: заголовку верить
    нельзя вовсе."""
    request = _request("1.2.3.4", remote="10.0.0.7")
    assert client_ip(request) == "10.0.0.7"


def test_num_proxies_is_set_in_base_settings():
    """Значение по умолчанию у DRF — None, и при нём заголовок клиента
    становится ключом throttling целиком. Настройка обязана быть задана."""
    from django.conf import settings

    assert settings.REST_FRAMEWORK["NUM_PROXIES"] is not None


# ------------------------------------------------------------- логи и ПДн


@pytest.mark.parametrize(
    ("phone", "expected"),
    [
        ("+79001234567", "+7900***4567"),
        ("+7900123", "***"),
        ("", "***"),
    ],
)
def test_mask_phone(phone, expected):
    assert mask_phone(phone) == expected


@pytest.mark.django_db(transaction=True)
def test_otp_request_does_not_log_phone_or_code(caplog, monkeypatch):
    """В логе не должно быть ни кода входа, ни телефона целиком: лог живёт
    дольше базы и доступен шире.

    `propagate` включаем руками: в настройках у логгера `apps` он выключен,
    и без этого записи не доходят до перехватчика pytest.
    """
    monkeypatch.setattr(logging.getLogger("apps"), "propagate", True)
    phone = "+79001234567"

    with caplog.at_level("INFO"):
        from apps.accounts.services import request_otp

        challenge = request_otp(phone)

    records = "\n".join(
        record.getMessage()
        for record in caplog.records
        # Провайдер console существует ровно для того, чтобы показать
        # сообщение целиком, — на проде его нет, и аудит это ловит.
        if record.name != "apps.notifications.providers.console"
    )
    assert phone not in records
    assert challenge.debug_code not in records
    assert "+7900***4567" in records


# ------------------------------------------------------------- SECRET_KEY


@pytest.mark.parametrize(
    "value",
    ["insecure-dev-key", "change-me-in-production-please-use-50-random-chars"],
)
def test_placeholder_secret_key_is_rejected(value):
    assert secret_key_problem(value) is not None


def test_short_secret_key_is_rejected():
    assert secret_key_problem("a" * 20) is not None


def test_own_long_secret_key_passes():
    assert secret_key_problem("x7" * 40) is None


# ---------------------------------------------------------- security_audit


@pytest.fixture
def prod_like(settings, tmp_path, monkeypatch):
    """Настройки, при которых аудит обязан быть зелёным целиком.

    Собраны здесь, а не в conftest: это единственное место, где нужна
    полная имитация прода, и держать её рядом с проверками нагляднее.
    """
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    monkeypatch.setenv("BOOTSTRAP_DEMO", "false")

    settings.DEBUG = False
    settings.SECRET_KEY = "z9" * 30
    settings.OTP = {**settings.OTP, "DEBUG_EXPOSE_CODE": False}
    settings.ALLOWED_HOSTS = ["moiservis.pro"]
    settings.CSRF_TRUSTED_ORIGINS = ["https://moiservis.pro"]
    settings.CORS_ALLOW_ALL_ORIGINS = False
    settings.CORS_ALLOWED_ORIGINS = ["https://moiservis.pro"]
    settings.SECURE_SSL_REDIRECT = True
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    settings.SECURE_CONTENT_TYPE_NOSNIFF = True
    settings.SECURE_HSTS_SECONDS = 31536000
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.SENTRY_DSN = "https://example@sentry.invalid/1"
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    settings.SMS = {
        **settings.SMS,
        "PROVIDER": "smsru",
        "API_KEY": "key",
        "SENDER": "MOISERVIS",
        "ENABLED_KINDS": ["otp"],
    }
    # Именно setitem, а не подмена DATABASES целиком: смена настройки БД
    # дёргает сигнал Django и закрывает соединение прямо посреди теста.
    monkeypatch.setitem(settings.DATABASES["default"], "PASSWORD", "S" * 24)

    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "autoservice-20990101-030000.dump").write_bytes(b"PGDMP\x00")
    settings.BACKUPS = {"DIR": backups, "KEEP_DAYS": 14, "MAX_AGE_HOURS": 36}
    return settings


def _levels(findings):
    return {finding.title: finding.level for finding in findings}


@pytest.mark.django_db
def test_audit_passes_on_healthy_production(prod_like):
    findings = security_audit.collect_findings()
    bad = [f for f in findings if f.level != security_audit.OK]
    assert bad == [], bad


@pytest.mark.django_db
def test_audit_catches_exposed_otp_code(prod_like, settings):
    settings.OTP = {**settings.OTP, "DEBUG_EXPOSE_CODE": True}
    assert _levels(security_audit.collect_findings())["OTP_DEBUG_EXPOSE_CODE"] == (
        security_audit.FAIL
    )


@pytest.mark.django_db
def test_audit_catches_console_sms_provider(prod_like, settings):
    settings.SMS = {**settings.SMS, "PROVIDER": "console"}
    assert _levels(security_audit.collect_findings())["SMS_PROVIDER"] == (
        security_audit.FAIL
    )


@pytest.mark.django_db
def test_audit_catches_spoofable_proxy_setting(prod_like, settings):
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": None}
    assert _levels(security_audit.collect_findings())["NUM_PROXIES"] == (
        security_audit.FAIL
    )


@pytest.mark.django_db
def test_audit_catches_demo_account_with_readme_password(prod_like):
    """Учётка опасна не фактом существования, а тем, что пускает по
    паролю, напечатанному в README."""
    User.objects.create(
        phone="+79000000000",
        role="admin",
        is_staff=True,
        password=make_password("admin12345"),
    )
    assert _levels(security_audit.collect_findings())["демо-учётка +79000000000"] == (
        security_audit.FAIL
    )


@pytest.mark.django_db
def test_audit_accepts_demo_phone_with_changed_password(prod_like):
    User.objects.create(
        phone="+79000000000",
        role="admin",
        is_staff=True,
        password=make_password("совсем другой пароль"),
    )
    assert _levels(security_audit.collect_findings())["демо-учётка +79000000000"] == (
        security_audit.OK
    )


@pytest.mark.django_db
def test_audit_catches_missing_backups(prod_like, tmp_path):
    prod_like.BACKUPS = {
        "DIR": tmp_path / "нет-такого-каталога",
        "KEEP_DAYS": 14,
        "MAX_AGE_HOURS": 36,
    }
    assert _levels(security_audit.collect_findings())["бэкапы PostgreSQL"] == (
        security_audit.FAIL
    )


@pytest.mark.django_db
def test_audit_catches_stale_backups(prod_like, tmp_path):
    """Снимок есть, но задание давно не выполняется. Молчать об этом
    опаснее, чем об отсутствии бэкапов вовсе: каталог не пуст, и глазами
    проблема не видна."""
    directory = tmp_path / "stale"
    directory.mkdir()
    dump = directory / "autoservice-20200101-030000.dump"
    dump.write_bytes(b"PGDMP\x00")
    old = time.time() - timedelta(days=5).total_seconds()
    os.utime(dump, (old, old))

    prod_like.BACKUPS = {"DIR": directory, "KEEP_DAYS": 14, "MAX_AGE_HOURS": 36}
    assert _levels(security_audit.collect_findings())["бэкапы PostgreSQL"] == (
        security_audit.FAIL
    )


@pytest.mark.django_db
def test_audit_command_fails_loudly(prod_like, settings):
    """Ненулевой код возврата — то, ради чего команду можно повесить в
    cron и не читать вывод глазами."""
    settings.DEBUG = True
    with pytest.raises(CommandError):
        call_command("security_audit")


@pytest.mark.django_db
def test_audit_command_succeeds_on_healthy_production(prod_like):
    call_command("security_audit")


@pytest.mark.django_db
def test_audit_strict_mode_treats_warnings_as_failures(prod_like, settings):
    settings.SENTRY_DSN = ""
    call_command("security_audit")  # без --strict предупреждение не валит
    with pytest.raises(CommandError):
        call_command("security_audit", "--strict")
