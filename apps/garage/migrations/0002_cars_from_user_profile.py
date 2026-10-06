"""Машина из профиля (`User.car_model`, `car_plate`) — первый автомобиль гаража.

Переносится всё непустое, у кого бы оно ни было: ничего не теряется. Номер
приводится к той же форме, что у новых машин (кириллица, без пробелов), —
иначе поиск по номеру не свёл бы старую машину с новой записью мастера.
Функция приведения повторена здесь, а не импортирована: миграция обязана
работать так же и через год, когда код сервиса изменится.

Обратно: основной автомобиль возвращается в профиль. Поля профиля к этому
моменту уже восстановлены откатом `accounts.0004` — он зависит от этой
миграции и откатывается раньше.
"""

import re

from django.db import migrations

_LAT = "ABEKMHOPCTYX"
_CYR = "АВЕКМНОРСТУХ"


def _plate(raw: str) -> str:
    value = re.sub(r"[\s\-]", "", raw or "").upper()
    letters = {ch for ch in value if ch.isalpha()}
    if letters and letters <= set(_LAT + _CYR):
        value = value.translate(str.maketrans(_LAT, _CYR))
    return value[:16]


def _title(raw: str) -> str:
    return " ".join((raw or "").split())[:120]


def forward(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Car = apps.get_model("garage", "Car")

    owners = (
        User.objects.exclude(car_model="", car_plate="")
        .exclude(cars__isnull=False)  # повторный прогон не плодит дублей
        .values_list("pk", "car_model", "car_plate")
    )
    Car.objects.bulk_create(
        [
            Car(user_id=pk, title=_title(model), plate=_plate(plate), is_primary=True)
            for pk, model, plate in owners.iterator()
            if _title(model) or _plate(plate)
        ],
        batch_size=500,
    )


def backward(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Car = apps.get_model("garage", "Car")

    cars = Car.objects.filter(archived_at__isnull=True).order_by("user_id", "-is_primary", "created_at")
    seen = set()
    for car in cars.iterator():
        if car.user_id in seen:
            continue
        seen.add(car.user_id)
        User.objects.filter(pk=car.user_id).update(car_model=car.title, car_plate=car.plate)


class Migration(migrations.Migration):
    dependencies = [
        ("garage", "0001_initial"),
        # Поля профиля ещё на месте: их удаляет accounts.0004 после нас.
        ("accounts", "0003_otp_verificahub"),
    ]

    operations = [migrations.RunPython(forward, backward)]
