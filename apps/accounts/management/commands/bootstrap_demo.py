"""Наполнение пустой базы данными, на которых можно щёлкать сценарий.

Команда идемпотентна: повторный запуск ничего не сломает и не задвоит.
Вызывается из docker-entrypoint при старте.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.constants import UserRole
from apps.accounts.models import User
from apps.catalog.models import Oil, OilStock, OilType, ServicePoint

POINTS = [
    {
        "name": "Северная",
        "address": "г. Москва, ул. Складочная, 1с18",
        "phone": "+74991234567",
        "opens_at": time(9, 0),
        "closes_at": time(21, 0),
        "posts_count": 2,
    },
    {
        "name": "Южная",
        "address": "г. Москва, Варшавское ш., 132",
        "phone": "+74991234568",
        "opens_at": time(10, 0),
        "closes_at": time(20, 0),
        "posts_count": 1,
    },
]

OILS = [
    {
        "brand": "Mobil",
        "name": "Super 3000 X1",
        "viscosity": "5W-40",
        "oil_type": OilType.SYNTHETIC,
        "volume_liters": Decimal("4.0"),
        "price": Decimal("4200"),
        "work_price": Decimal("900"),
        "description": "Синтетика для бензиновых и дизельных двигателей.",
    },
    {
        "brand": "Shell",
        "name": "Helix HX8",
        "viscosity": "5W-30",
        "oil_type": OilType.SYNTHETIC,
        "volume_liters": Decimal("4.0"),
        "price": Decimal("3900"),
        "work_price": Decimal("900"),
        "description": "Универсальная синтетика, подходит большинству легковых.",
    },
    {
        "brand": "Lukoil",
        "name": "Genesis Armortech",
        "viscosity": "5W-40",
        "oil_type": OilType.SYNTHETIC,
        "volume_liters": Decimal("4.0"),
        "price": Decimal("2800"),
        "work_price": Decimal("800"),
        "description": "Бюджетная синтетика.",
    },
    {
        "brand": "Total",
        "name": "Quartz 7000",
        "viscosity": "10W-40",
        "oil_type": OilType.SEMI_SYNTHETIC,
        "volume_liters": Decimal("5.0"),
        "price": Decimal("2400"),
        "work_price": Decimal("800"),
        "description": "Полусинтетика для пробега свыше 150 тыс. км.",
    },
]


class Command(BaseCommand):
    help = "Создаёт демо-точки, масла, остатки и учётные записи сотрудников"

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        points = []
        for data in POINTS:
            point, created = ServicePoint.objects.get_or_create(
                name=data["name"],
                defaults={**data, "workdays": [0, 1, 2, 3, 4, 5, 6], "slot_minutes": 30},
            )
            points.append(point)
            self.stdout.write(f"{'+' if created else '='} точка {point.name}")

        oils = []
        for data in OILS:
            oil, created = Oil.objects.get_or_create(
                brand=data["brand"],
                name=data["name"],
                viscosity=data["viscosity"],
                volume_liters=data["volume_liters"],
                defaults=data,
            )
            oils.append(oil)
            self.stdout.write(f"{'+' if created else '='} масло {oil}")

        for point in points:
            for index, oil in enumerate(oils):
                # Разные остатки, чтобы сразу было видно, что склад по точкам разный.
                OilStock.objects.get_or_create(
                    service_point=point,
                    oil=oil,
                    defaults={"quantity": 10 - index * 2},
                )

        master, created = User.objects.get_or_create(
            phone="+79000000001",
            defaults={
                "full_name": "Мастер Иванов",
                "role": UserRole.MASTER,
                "is_staff": True,
            },
        )
        if created:
            master.set_password("master12345")
            master.save(update_fields=["password"])
        self.stdout.write(f"{'+' if created else '='} мастер {master.phone} / master12345")

        admin, created = User.objects.get_or_create(
            phone="+79000000000",
            defaults={
                "full_name": "Администратор",
                "role": UserRole.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin.set_password("admin12345")
            admin.save(update_fields=["password"])
        self.stdout.write(f"{'+' if created else '='} админ {admin.phone} / admin12345")

        self.stdout.write(self.style.SUCCESS("Демо-данные готовы"))
