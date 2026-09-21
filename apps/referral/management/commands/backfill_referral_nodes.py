"""Выдать код приглашения всем, кто зарегистрировался до запуска программы.

Узел заводится при регистрации, а на боевом сервере клиенты появились
раньше этого кода. Ленивое создание в API спасло бы каждого по отдельности
— но только когда он сам откроет экран. Команда закрывает разрыв разом,
чтобы код был у всех и в админке, и в выгрузках.

    docker compose … exec api python manage.py backfill_referral_nodes

Повторный запуск безопасен: у кого узел есть, того не трогаем.
"""

from django.core.management.base import BaseCommand

from apps.accounts.constants import UserRole
from apps.accounts.models import User
from apps.referral.services import tree


class Command(BaseCommand):
    help = "Создать узлы в реферальной матрице клиентам, у которых их нет"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="только посчитать, ничего не создавая",
        )

    def handle(self, *args, **options):
        missing = User.objects.filter(
            role=UserRole.CLIENT, referral_node__isnull=True
        ).order_by("date_joined")
        total = missing.count()

        if options["dry_run"]:
            self.stdout.write(f"Клиентов без узла: {total}")
            return

        created = 0
        for user in missing.iterator():
            tree.ensure_node(user)
            created += 1

        self.stdout.write(
            self.style.SUCCESS(f"Создано узлов: {created} (из {total} найденных)")
        )
