"""Витрина: цифры, сроки и телефонные ссылки берутся из настроек, а не из вёрстки."""

from __future__ import annotations

import pytest

from apps.web.templatetags.web_tags import ru_before, ru_plural, tel_href

FORMS = "адрес,адреса,адресов"


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, "адрес"), (2, "адреса"), (4, "адреса"), (5, "адресов"),
        (11, "адресов"), (12, "адресов"), (14, "адресов"), (21, "адрес"),
        (22, "адреса"), (111, "адресов"), (0, "адресов"),
    ],
)
def test_ru_plural(n, expected):
    assert ru_plural(n, FORMS) == expected


def test_tel_href_keeps_only_digits_and_plus():
    assert tel_href("+7 (499) 123-45-67") == "+74991234567"
    assert tel_href("8 900 111 22 33") == "89001112233"
    assert tel_href("") == ""


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(60, "час"), (120, "2 часа"), (300, "5 часов"), (90, "90 минут"), (1, "1 минуту")],
)
def test_ru_before(minutes, expected):
    assert ru_before(minutes) == expected


# ------------------------------------------------------------ страница целиком
def _landing(client) -> str:
    response = client.get("/")
    assert response.status_code == 200
    return response.content.decode()


@pytest.mark.django_db
def test_landing_shows_no_invented_figures_by_default(client, settings, point):
    """Без настроек в шапке нет ни «лет на рынке», ни оценки.

    Раньше оценка 4,9 была зашита в шаблон, хотя отзывов система не
    собирает, а годы и число машин имели выдуманные значения по умолчанию.
    """
    settings.COMPANY = {
        **settings.COMPANY, "YEARS_ON_MARKET": 0, "CARS_SERVED": 0, "RATING": 0.0,
    }
    html = _landing(client)

    assert "hero-stats" not in html
    assert "4,9" not in html
    assert "на рынке" not in html


@pytest.mark.django_db
def test_landing_shows_only_configured_figures(client, settings, point):
    settings.COMPANY = {
        **settings.COMPANY,
        "YEARS_ON_MARKET": 3, "CARS_SERVED": 0,
        "RATING": 4.8, "RATING_SOURCE": "Яндекс Картах",
    }
    html = _landing(client)

    assert "3</b><span>года на рынке" in html
    assert "машин обслужено" not in html
    assert 'data-count="4.8"' in html
    assert "оценка на Яндекс Картах" in html


@pytest.mark.django_db
def test_landing_pluralizes_address_count(client, point):
    """Одна точка — «1 адрес», а не «1 адреса»."""
    html = _landing(client)
    assert "1 адрес в городе" in html


@pytest.mark.django_db
def test_landing_promises_follow_booking_settings(client, settings, point):
    settings.BOOKING = {
        **settings.BOOKING, "CANCEL_DEADLINE_MINUTES": 120, "REMINDER_LEAD_MINUTES": 180,
    }
    settings.SMS = {**settings.SMS, "ENABLED_KINDS": ["otp", "booking_reminder"]}
    html = _landing(client)

    assert "не позже чем за 2 часа до визита" in html
    assert "Напомним за 3 часа" in html
    assert "за час до визита" not in html


@pytest.mark.django_db
def test_landing_does_not_promise_reminder_when_it_is_off(client, settings, point):
    settings.SMS = {**settings.SMS, "ENABLED_KINDS": ["otp"]}
    assert "Напомним" not in _landing(client)


@pytest.mark.django_db
def test_landing_phone_links_are_dialable(client, settings, point):
    settings.COMPANY = {**settings.COMPANY, "PHONE": "+7 (499) 123-45-67"}
    html = _landing(client)

    assert 'href="tel:+74991234567"' in html
    assert 'href="tel:+7 (499)' not in html


# ------------------------------------------------------ веб-приложение /app/
def test_web_app_page_has_everything_for_iphone(client):
    response = client.get("/app/")
    html = response.content.decode()

    assert response.status_code == 200
    assert 'rel="manifest" href="/app/manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert 'name="apple-mobile-web-app-capable" content="yes"' in html
    assert "viewport-fit=cover" in html
    # Модули подключаются картой импорта с адресами из {% static %}: в проде
    # в них хеш содержимого, и обновление доезжает до телефона.
    assert '<script type="importmap">' in html
    assert '"app/main": "/static/web/app/main.js"' in html
    assert 'id="app-config"' in html


def test_web_app_manifest(client):
    response = client.get("/app/manifest.webmanifest")
    data = response.json()

    assert response["Content-Type"].startswith("application/manifest+json")
    assert data["start_url"] == "/app/"
    assert data["scope"] == "/app/"
    assert data["display"] == "standalone"
    assert {icon["sizes"] for icon in data["icons"]} == {"192x192", "512x512"}
    assert any(icon.get("purpose") == "maskable" for icon in data["icons"])


def test_web_app_service_worker(client):
    response = client.get("/app/sw.js")
    body = response.content.decode()

    assert response["Content-Type"].startswith("application/javascript")
    assert response["Service-Worker-Allowed"] == "/app/"
    # Сам воркер кешировать нельзя — иначе новая версия не установится.
    assert response["Cache-Control"] == "no-cache"
    assert "/static/web/app/main.js" in body
    assert "/api/" not in body.split("const ASSETS")[1].split(";")[0]


@pytest.mark.django_db
def test_landing_offers_web_app_for_iphone(client, settings, point):
    settings.COMPANY = {**settings.COMPANY, "APP_STORE_URL": ""}
    html = _landing(client)

    assert 'href="/app/"' in html
    assert "Веб-приложение" in html


@pytest.mark.django_db
def test_invite_page_passes_code_to_web_app(client):
    from apps.accounts.models import User
    from apps.referral.services import tree as tree_service

    user = User.objects.create_user(phone="+79005550000", full_name="Друг")
    node = tree_service.ensure_node(user)

    html = client.get(f"/i/{node.code}/").content.decode()

    assert f'href="/app/?invite={node.code}"' in html
