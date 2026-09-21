"""Загрузка справочника марок и моделей из текстового файла.

Справочник лежит текстом (`apps/catalog/data/cars.txt`), а не фикстурой и
не миграцией данных, по двум причинам. Его правит человек, которому не
нужно знать ни JSON, ни Django. И он будет пополняться — новые марки
появляются каждый год, а миграция данных, которую переписывают, перестаёт
быть миграцией.

    docker compose … exec api python manage.py import_cars

Повторный запуск безопасен: существующие записи обновляются, ничего не
удаляется. Снятые с продажи марки убираются галочкой `is_active` в
админке — удалять их нельзя, на них ссылаются профили клиентов.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import CarMake, CarModel

DEFAULT_PATH = Path(settings.BASE_DIR) / "apps" / "catalog" / "data" / "cars.txt"


class Command(BaseCommand):
    help = "Загрузить марки и модели автомобилей из apps/catalog/data/cars.txt"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=str(DEFAULT_PATH),
            help="другой файл в том же формате",
        )
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            help="снять галочку «показывать» с марок, которых нет в файле",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"Файл не найден: {path}")

        makes = 0
        models = 0
        seen: list[str] = []

        with transaction.atomic():
            for order, line in enumerate(_rows(path), start=1):
                name, terms, model_names = line
                make, _ = CarMake.objects.update_or_create(
                    name=name,
                    defaults={
                        "search_terms": terms,
                        # Порядок строк в файле и есть порядок в списке:
                        # так автор справочника управляет выдачей, не
                        # проставляя числа руками.
                        "sort_order": order,
                        "is_active": True,
                    },
                )
                makes += 1
                seen.append(name)

                for model_name in model_names:
                    CarModel.objects.update_or_create(
                        make=make,
                        name=model_name,
                        defaults={"is_active": True},
                    )
                    models += 1

            if options["deactivate_missing"]:
                hidden = CarMake.objects.exclude(name__in=seen).update(is_active=False)
                self.stdout.write(f"Скрыто марок, которых нет в файле: {hidden}")

        self.stdout.write(
            self.style.SUCCESS(f"Загружено: марок {makes}, моделей {models}")
        )


def _rows(path: Path):
    """Разбор файла: `Марка | синонимы | модели через запятую`."""
    with path.open(encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 3:
                raise CommandError(
                    f"{path}:{number}: ожидалось три части через «|», "
                    f"получено {len(parts)}"
                )

            name, terms, models = parts
            if not name:
                raise CommandError(f"{path}:{number}: пустое название марки")

            model_names = [item.strip() for item in models.split(",") if item.strip()]
            yield name, terms, model_names
