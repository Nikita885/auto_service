"""Аудит боевых настроек одной командой.

Чек-лист перед продом жил только в README, то есть проверялся глазами и по
памяти. Глазами он проверяется ровно один раз — в день запуска; дальше
`.env` правят, контейнеры пересоздают, и никто не замечает, что
`SMS_PROVIDER` вернулся в `console`, а бэкапы не снимались две недели.

Команда запускается на сервере, внутри того же контейнера, что и
приложение, — значит видит именно те настройки, с которыми работает сайт,
а не те, что написаны в файле:

    docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api
        python manage.py security_audit

Код возврата 1, если хоть одна проверка провалена, — чтобы команду можно
было повесить в cron и не читать вывод глазами.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.common.secret_key import secret_key_problem

OK = "OK"
WARN = "ВНИМАНИЕ"
FAIL = "ПРОВАЛ"

# Пароли демо-учёток напечатаны в README, то есть публичны. Проверяем не
# «существует ли пользователь», а «пускает ли его известный всем пароль»:
# телефон демо-админа мог достаться и живому клиенту.
DEMO_ACCOUNTS = {
    "+79000000000": "admin12345",
    "+79000000001": "master12345",
}

WEAK_DB_PASSWORDS = frozenset({"", "autoservice", "postgres", "password", "changeme"})

MIN_DB_PASSWORD_LENGTH = 16


@dataclass(frozen=True)
class Finding:
    level: str
    title: str
    detail: str = ""


def _check_settings_module() -> Finding:
    module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    if module.endswith(".prod"):
        return Finding(OK, "DJANGO_SETTINGS_MODULE", module)
    return Finding(
        FAIL,
        "DJANGO_SETTINGS_MODULE",
        f"{module or '(не задан)'} — ожидается config.settings.prod. "
        "Проверки ниже относятся к настройкам, которых на проде нет",
    )


def _check_debug() -> Finding:
    if settings.DEBUG:
        return Finding(
            FAIL, "DEBUG", "включён: страницы ошибок показывают код и настройки"
        )
    return Finding(OK, "DEBUG", "выключен")


def _check_secret_key() -> Finding:
    problem = secret_key_problem(settings.SECRET_KEY)
    if problem is None:
        return Finding(OK, "SECRET_KEY", "свой, достаточной длины")
    # Значение из репозитория прод вообще не пускает (settings/prod.py), так
    # что сюда доходит в основном замечание о длине.
    return Finding(WARN, "SECRET_KEY", problem)


def _check_otp_expose() -> Finding:
    if settings.OTP["DEBUG_EXPOSE_CODE"]:
        return Finding(
            FAIL,
            "OTP_DEBUG_EXPOSE_CODE",
            "код входа отдаётся в ответе API — это вход в любой аккаунт "
            "по одному номеру телефона",
        )
    return Finding(OK, "OTP_DEBUG_EXPOSE_CODE", "код в ответе API не отдаётся")


def _check_debug_phones() -> Finding:
    """Временная заглушка на время, пока не работают SMS.

    Каждый номер в списке — открытая дверь в этот аккаунт: код входа
    возвращается прямо в ответе API, и запросить его может кто угодно.
    Провал, а не предупреждение: заглушка обязана мозолить глаза, пока её
    не уберут.
    """
    phones = settings.OTP.get("DEBUG_PHONES") or []
    if not phones:
        return Finding(OK, "OTP_DEBUG_PHONES", "пусто")
    return Finding(
        FAIL,
        "OTP_DEBUG_PHONES",
        f"код входа отдаётся в ответе API для {', '.join(phones)} — "
        "временная заглушка, уберите её сразу после запуска SMS",
    )


def _check_hosts() -> list[Finding]:
    found = []

    hosts = settings.ALLOWED_HOSTS
    if not hosts:
        found.append(Finding(FAIL, "ALLOWED_HOSTS", "пуст"))
    elif "*" in hosts:
        found.append(
            Finding(FAIL, "ALLOWED_HOSTS", "содержит звёздочку: принимается любой Host")
        )
    else:
        found.append(Finding(OK, "ALLOWED_HOSTS", ", ".join(hosts)))

    origins = settings.CSRF_TRUSTED_ORIGINS
    if not origins:
        found.append(
            Finding(
                FAIL,
                "CSRF_TRUSTED_ORIGINS",
                "пуст — за HTTPS вход в админку и панели отдаёт 403",
            )
        )
    elif any(not origin.startswith("https://") for origin in origins):
        found.append(Finding(WARN, "CSRF_TRUSTED_ORIGINS", "есть адреса не на https"))
    else:
        found.append(Finding(OK, "CSRF_TRUSTED_ORIGINS", ", ".join(origins)))

    if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False):
        found.append(
            Finding(FAIL, "CORS", "CORS_ALLOW_ALL_ORIGINS включён — открыт всем")
        )
    else:
        found.append(
            Finding(OK, "CORS", ", ".join(settings.CORS_ALLOWED_ORIGINS) or "список пуст")
        )

    return found


def _check_transport() -> list[Finding]:
    """Настройки, делающие HTTPS обязательным, а cookie — недоступными по
    HTTP. По отдельности каждая выглядит мелочью, вместе они и есть защита
    сессии администратора."""
    expectations = [
        ("SECURE_SSL_REDIRECT", "HTTP не редиректится на HTTPS"),
        ("SESSION_COOKIE_SECURE", "cookie сессии уедет по HTTP"),
        ("CSRF_COOKIE_SECURE", "CSRF-cookie уедет по HTTP"),
        ("SECURE_CONTENT_TYPE_NOSNIFF", "браузер угадывает тип содержимого"),
    ]
    found = [
        Finding(OK, name, "включено")
        if getattr(settings, name, False)
        else Finding(FAIL, name, why)
        for name, why in expectations
    ]

    if getattr(settings, "SECURE_HSTS_SECONDS", 0) < 31536000:
        found.append(Finding(WARN, "SECURE_HSTS_SECONDS", "меньше года или не задан"))
    else:
        found.append(Finding(OK, "SECURE_HSTS_SECONDS", "год"))

    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None) is None:
        found.append(
            Finding(
                FAIL,
                "SECURE_PROXY_SSL_HEADER",
                "не задан — за nginx получится петля редиректов",
            )
        )
    else:
        found.append(Finding(OK, "SECURE_PROXY_SSL_HEADER", "задан"))

    return found


def _check_proxy_count() -> Finding:
    """Ключ throttling считается по X-Forwarded-For, а писать этот заголовок
    начинает сам клиент. Если не сказать DRF, сколько своих прокси стоит
    впереди, лимит по IP обходится подстановкой заголовка."""
    num = settings.REST_FRAMEWORK.get("NUM_PROXIES")
    if num is None:
        return Finding(
            FAIL,
            "NUM_PROXIES",
            "не задан: DRF доверяет X-Forwarded-For целиком, и лимит "
            "«10 кодов в час на IP» обходится сменой заголовка",
        )
    if num == 0:
        return Finding(
            WARN,
            "NUM_PROXIES",
            "0 — считается REMOTE_ADDR. За nginx он у всех 127.0.0.1, то есть "
            "лимит на один IP становится лимитом на весь сайт",
        )
    return Finding(OK, "NUM_PROXIES", str(num))


def _check_throttling() -> list[Finding]:
    rates = settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {})
    found = []
    for scope in ("otp_request", "otp_verify"):
        rate = rates.get(scope)
        if rate:
            found.append(Finding(OK, f"throttle {scope}", rate))
        else:
            found.append(Finding(FAIL, f"throttle {scope}", "лимит не задан"))
    return found


def _check_sms() -> list[Finding]:
    conf = settings.SMS
    found = []

    if conf["PROVIDER"] == "console":
        found.append(
            Finding(
                FAIL,
                "SMS_PROVIDER",
                "console — сообщения не уходят, а печатаются в лог контейнера "
                "вместе с кодами входа",
            )
        )
    else:
        found.append(Finding(OK, "SMS_PROVIDER", conf["PROVIDER"]))
        if conf["API_KEY"]:
            found.append(Finding(OK, "SMS_API_KEY", "задан"))
        else:
            found.append(Finding(FAIL, "SMS_API_KEY", "пуст"))
        if conf["SENDER"]:
            found.append(Finding(OK, "SMS_SENDER", conf["SENDER"]))
        else:
            found.append(
                Finding(
                    FAIL,
                    "SMS_SENDER",
                    "пуст — шлюз ответит 221 и не пропустит ни одного "
                    "сообщения, то есть войти в приложение будет нельзя",
                )
            )

    if "otp" in conf["ENABLED_KINDS"]:
        found.append(Finding(OK, "SMS_ENABLED_KINDS", ", ".join(conf["ENABLED_KINDS"])))
    else:
        found.append(
            Finding(
                FAIL,
                "SMS_ENABLED_KINDS",
                "нет otp — код входа никому не уходит, вход в приложение закрыт",
            )
        )

    return found


def _check_db_password() -> Finding:
    password = settings.DATABASES["default"]["PASSWORD"]
    if password in WEAK_DB_PASSWORDS:
        return Finding(FAIL, "POSTGRES_PASSWORD", "значение из примера конфига")
    if len(password) < MIN_DB_PASSWORD_LENGTH:
        return Finding(
            WARN, "POSTGRES_PASSWORD", f"короче {MIN_DB_PASSWORD_LENGTH} символов"
        )
    return Finding(OK, "POSTGRES_PASSWORD", "свой, достаточной длины")


def _check_bootstrap_demo() -> Finding:
    value = os.environ.get("BOOTSTRAP_DEMO", "true").lower()
    if value == "true":
        return Finding(
            FAIL,
            "BOOTSTRAP_DEMO",
            "true — при каждом старте api заново создаются учётки с паролями "
            "из README",
        )
    return Finding(OK, "BOOTSTRAP_DEMO", value)


def _check_demo_accounts() -> list[Finding]:
    user_model = get_user_model()
    found = []
    for phone, password in DEMO_ACCOUNTS.items():
        user = user_model.objects.filter(phone=phone).first()
        if user is None:
            found.append(Finding(OK, f"демо-учётка {phone}", "нет"))
        elif user.check_password(password):
            found.append(
                Finding(
                    FAIL,
                    f"демо-учётка {phone}",
                    "пускает по паролю из README — смените пароль или удалите "
                    "пользователя",
                )
            )
        else:
            found.append(Finding(OK, f"демо-учётка {phone}", "пароль изменён"))
    return found


def _check_backups() -> Finding:
    conf = settings.BACKUPS
    directory = Path(conf["DIR"])
    dumps = list(directory.glob("*.dump")) if directory.is_dir() else []
    if not dumps:
        return Finding(
            FAIL,
            "бэкапы PostgreSQL",
            f"в {directory} нет ни одного снимка. Поставьте deploy/backup.sh "
            "в cron — отказ диска сейчас означает потерю клиентской базы и "
            "всей истории записей",
        )

    newest = max(dumps, key=lambda path: path.stat().st_mtime)
    made_at = datetime.fromtimestamp(newest.stat().st_mtime, tz=UTC)
    age = datetime.now(tz=UTC) - made_at
    human = f"{newest.name}, возраст {int(age.total_seconds() // 3600)} ч"

    if age > timedelta(hours=conf["MAX_AGE_HOURS"]):
        return Finding(
            FAIL,
            "бэкапы PostgreSQL",
            f"последний снимок старше {conf['MAX_AGE_HOURS']} ч ({human}) — "
            "задание, скорее всего, не выполняется",
        )
    return Finding(OK, "бэкапы PostgreSQL", f"{len(dumps)} шт., последний — {human}")


def _check_sentry() -> Finding:
    if getattr(settings, "SENTRY_DSN", ""):
        return Finding(OK, "SENTRY_DSN", "задан")
    return Finding(WARN, "SENTRY_DSN", "не задан — ошибки прода видны только в логах")


def _check_service_points() -> list[Finding]:
    """Настройки точек, без которых запись не работает.

    Неверный часовой пояс или рабочие дни не видны на сайте, пока клиент не
    дойдёт до выбора времени, — и тогда он получает ошибку. Ловим заранее.
    """
    from django.core.exceptions import ValidationError as DjangoValidationError

    from apps.catalog.models import ServicePoint, validate_timezone, validate_workdays

    findings: list[Finding] = []
    for point in ServicePoint.objects.filter(is_active=True):
        problems = []
        for validator, value, label in (
            (validate_timezone, point.timezone, "часовой пояс"),
            (validate_workdays, point.workdays, "рабочие дни"),
        ):
            try:
                validator(value)
            except DjangoValidationError:
                problems.append(f"{label} {value!r}")
        if problems:
            detail = "неверно: " + ", ".join(problems)
            findings.append(Finding(FAIL, f"точка «{point.name}»", detail))
    if not findings:
        findings.append(Finding(OK, "настройки точек", "часовые пояса и рабочие дни в порядке"))
    return findings


def collect_findings() -> list[Finding]:
    """Все проверки по порядку. Список плоский: команда не решает, что важнее,
    — важно всё, что помечено ПРОВАЛ."""
    findings: list[Finding] = [
        _check_settings_module(),
        _check_debug(),
        _check_secret_key(),
        _check_otp_expose(),
        _check_debug_phones(),
    ]
    findings += _check_hosts()
    findings += _check_transport()
    findings.append(_check_proxy_count())
    findings += _check_throttling()
    findings += _check_sms()
    findings.append(_check_db_password())
    findings.append(_check_bootstrap_demo())
    findings += _check_demo_accounts()
    findings += _check_service_points()
    findings.append(_check_backups())
    findings.append(_check_sentry())
    return findings


class Command(BaseCommand):
    help = "Проверить боевые настройки по чек-листу перед продом"

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="считать предупреждения провалом (для cron)",
        )

    def handle(self, *args, **options):
        findings = collect_findings()

        styles = {
            OK: self.style.SUCCESS,
            WARN: self.style.WARNING,
            FAIL: self.style.ERROR,
        }
        for finding in findings:
            mark = styles[finding.level](f"[{finding.level:^8}]")
            tail = f" — {finding.detail}" if finding.detail else ""
            self.stdout.write(f"{mark} {finding.title}{tail}")

        failed = [f for f in findings if f.level == FAIL]
        warned = [f for f in findings if f.level == WARN]
        self.stdout.write(
            f"\nПроверок: {len(findings)}, провалено: {len(failed)}, "
            f"предупреждений: {len(warned)}"
        )

        if failed or (options["strict"] and warned):
            raise CommandError("Чек-лист не пройден")

        self.stdout.write(self.style.SUCCESS("Чек-лист пройден"))
