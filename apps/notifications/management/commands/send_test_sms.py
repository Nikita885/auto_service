"""Проверка SMS-шлюза одной командой; с `--call` — звонка с кодом входа.

Нужна, чтобы убедиться в работоспособности ключа и имени отправителя, не
проходя весь сценарий входа и не тратя код из OTP. Отправка синхронная,
мимо Celery: ошибка шлюза должна вылететь в терминал целиком, а не осесть
в логе воркера.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.common.phone import normalize_phone
from apps.notifications.providers import (
    SmsDeliveryError,
    SmsRejectedError,
    get_sms_provider,
)
from apps.notifications.providers.call import get_call_provider


class Command(BaseCommand):
    help = (
        "Отправить тестовое SMS: manage.py send_test_sms +79001234567; "
        "позвонить с кодом входа: manage.py send_test_sms +79001234567 --call"
    )

    def add_arguments(self, parser):
        parser.add_argument("phone", help="номер получателя в любом формате")
        parser.add_argument(
            "--text",
            default="Проверка связи. Это тестовое сообщение сервиса.",
            help="текст сообщения",
        )
        parser.add_argument(
            "--call",
            action="store_true",
            help="вместо SMS заказать звонок с кодом (как при входе), 0,40 ₽",
        )

    def handle(self, *args, **options):
        phone = normalize_phone(options["phone"])
        if options["call"]:
            self._call(phone)
            return
        provider_name = settings.SMS["PROVIDER"]

        self.stdout.write(f"Провайдер: {provider_name}")
        self.stdout.write(f"Имя отправителя: {settings.SMS['SENDER'] or '(не задано)'}")
        self.stdout.write(f"Получатель: {phone}")

        # «Отправлено» на console выглядит как успех, хотя сообщение только
        # напечаталось в лог. Перепутать провайдера легко: SMS_PROVIDER
        # правится в .env на сервере, а команда запускается там же.
        if provider_name == "console":
            self.stdout.write(
                self.style.WARNING(
                    "\nВНИМАНИЕ: провайдер console — сообщение НЕ уходит в сеть,"
                    " а печатается в лог.\n"
                    "Для боевой отправки задайте в .env SMS_PROVIDER=smsru и"
                    " SMS_API_KEY, затем пересоздайте контейнеры"
                    " (up -d, а не restart).\n"
                )
            )

        provider = get_sms_provider()
        try:
            message_id = provider.send(phone, options["text"])
        except SmsRejectedError as exc:
            raise CommandError(f"Шлюз отказал: {exc}") from exc
        except SmsDeliveryError as exc:
            raise CommandError(f"Шлюз недоступен: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Отправлено, id сообщения: {message_id}"))

    def _call(self, phone: str) -> None:
        provider_name = settings.OTP["CALL_PROVIDER"]
        self.stdout.write(f"Провайдер звонков: {provider_name}")
        self.stdout.write(f"Получатель: {phone}")
        if provider_name == "console":
            self.stdout.write(
                self.style.WARNING(
                    "\nВНИМАНИЕ: провайдер console — никто не позвонит, код"
                    " печатается в лог.\nДля боевых звонков задайте в .env"
                    " OTP_CALL_PROVIDER=smsru и SMS_API_KEY, затем пересоздайте"
                    " контейнеры (up -d, а не restart).\n"
                )
            )
        try:
            placed = get_call_provider().call(phone, None)
        except SmsRejectedError as exc:
            raise CommandError(f"Шлюз отказал: {exc}") from exc
        except SmsDeliveryError as exc:
            raise CommandError(f"Шлюз недоступен: {exc}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Звонок заказан, id {placed.call_id}. Код — последние цифры"
                f" входящего номера: {placed.code}"
            )
        )
