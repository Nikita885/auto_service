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


IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "Version/17.5 Mobile Safari/604.1"
)
ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 "
    "Mobile Safari/537.36"
)
DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
PLAY = "https://play.google.com/store/apps/details?id=ru.autoservice.client"


@pytest.fixture
def stores(settings):
    settings.COMPANY = {**settings.COMPANY, "APP_STORE_URL": "", "GOOGLE_PLAY_URL": PLAY}


@pytest.mark.django_db
def test_iphone_sees_only_iphone_install(client, stores, point):
    html = client.get("/", HTTP_USER_AGENT=IPHONE).content.decode()

    assert 'href="/app/?install=1"' in html
    assert "Google Play" not in html
    # Главные кнопки на iPhone ведут туда же — к установке, а не к якорю.
    assert html.count('href="/app/?install=1"') >= 3


@pytest.mark.django_db
def test_android_sees_only_google_play(client, stores, point):
    html = client.get("/", HTTP_USER_AGENT=ANDROID).content.decode()

    assert PLAY in html
    assert "/app/?install=1" not in html
    assert "Для iPhone" not in html


@pytest.mark.django_db
def test_desktop_sees_both_ways(client, stores, point):
    html = client.get("/", HTTP_USER_AGENT=DESKTOP).content.decode()

    assert "/app/?install=1" in html
    assert PLAY in html


@pytest.mark.django_db
def test_invite_page_passes_code_to_both_apps(client, stores):
    from apps.accounts.models import User
    from apps.referral.services import tree as tree_service

    user = User.objects.create_user(phone="+79005550000", full_name="Друг")
    node = tree_service.ensure_node(user)

    iphone = client.get(f"/i/{node.code}/", HTTP_USER_AGENT=IPHONE).content.decode()
    android = client.get(f"/i/{node.code}/", HTTP_USER_AGENT=ANDROID).content.decode()

    assert f'href="/app/?install=1&amp;invite={node.code}"' in iphone
    # Google Play получает код в referrer: приложение прочитает его после установки.
    assert f"referrer=invite%3D{node.code}" in android


def test_manifest_keeps_invite_in_start_url(client):
    """iPhone запоминает start_url при «На экран „Домой“» — код доедет до
    установленного приложения, хотя хранилище у него своё."""
    page = client.get("/app/?invite=abc123").content.decode()
    assert 'href="/app/manifest.webmanifest?invite=ABC123"' in page

    data = client.get("/app/manifest.webmanifest?invite=ABC123").json()
    assert data["start_url"] == "/app/?invite=ABC123"


def test_manifest_ignores_garbage_invite(client):
    data = client.get('/app/manifest.webmanifest?invite=<script>').json()
    assert data["start_url"] == "/app/"


def _app_config(client, **extra):
    import json
    import re

    html = client.get("/app/?invite=ABC123", **extra).content.decode()
    pattern = r'<script id="app-config" type="application/json">(.*?)</script>'
    raw = re.search(pattern, html).group(1)
    return json.loads(raw)


def test_web_app_is_not_usable_from_browser_in_production(client, settings):
    """Только установленное на главный экран: из Safari — инструкция, без входа."""
    settings.DEBUG = False
    assert _app_config(client)["allowBrowser"] is False


def test_web_app_sends_android_to_play_with_invite(client, stores):
    config = _app_config(client, HTTP_USER_AGENT=ANDROID)
    assert config["playUrl"] == PLAY + "&referrer=invite%3DABC123"
