"""Техническая проверка перед заполнением и отправкой релиза в Play Console."""

import re
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Проверить технические условия Google Play; не заменяет модерацию"

    def handle(self, *args, **options):
        company = settings.COMPANY
        gradle = Path(settings.BASE_DIR) / "mobile/android/app/build.gradle"
        source = gradle.read_text(encoding="utf-8")
        target = re.search(r"targetSdk\s+(\d+)", source)
        checks = {
            "targetSdk >= 36": bool(target and int(target.group(1)) >= 36),
            "HTTPS сайта": urlsplit(company["SITE_URL"]).scheme == "https",
            "название приложения": bool(company["NAME"]) and len(company["NAME"]) <= 30,
            "владелец": bool(company.get("LEGAL_NAME")),
            "email поддержки": bool(company.get("EMAIL")) and "example.com" not in company["EMAIL"],
            "политика утверждена владельцем": settings.PRIVACY_POLICY_APPROVED,
            "отпечаток подписи App Links": bool(settings.ANDROID_APP["FINGERPRINTS"]),
            "DEBUG выключен": not settings.DEBUG,
            "коды входа не раскрываются": not settings.OTP["DEBUG_EXPOSE_CODE"]
            and not settings.OTP["DEBUG_PHONES"],
        }
        for label, ok in checks.items():
            self.stdout.write(f"[{'OK' if ok else 'НЕ ГОТОВО'}] {label}")
        self.stdout.write(
            "Отдельно: подпись AAB, Data safety, доступ модератора, рейтинг контента, "
            "тестирование и Pre-launch report в Play Console; политика хранения данных "
            "и удаление во внешних системах."
        )
        if not all(checks.values()):
            raise CommandError("Релиз пока не готов к отправке")
