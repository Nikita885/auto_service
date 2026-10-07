"""Автомобили клиента: добавить, поправить, сделать основным, удалить.

Все изменения одного клиента идут под блокировкой строки его аккаунта:
«первый автомобиль становится основным» и «основной ровно один» —
правила на несколько строк, и два параллельных запроса иначе сделали бы
основными оба (уникальный индекс поймал бы это пятисоткой).
"""

from __future__ import annotations

import re
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import CarModel
from apps.common.exceptions import ConflictError, NotFoundError, ValidationError
from apps.garage.models import Car

# Буквы российского номера бывают только эти двенадцать — у них есть
# латинские двойники. Клиент набирает «A123BC» латиницей, мастер —
# «А123ВС» кириллицей; без приведения поиск по номеру их не сведёт.
_PLATE_LETTERS_LAT = "ABEKMHOPCTYX"
_PLATE_LETTERS_CYR = "АВЕКМНОРСТУХ"
_LAT_TO_CYR = str.maketrans(_PLATE_LETTERS_LAT, _PLATE_LETTERS_CYR)
_CYR_TO_LAT = str.maketrans(_PLATE_LETTERS_CYR, _PLATE_LETTERS_LAT)

# VIN — 17 знаков, латиница без I, O и Q (их путают с 1 и 0).
_VIN_RE = re.compile(r"[A-HJ-NPR-Z0-9]{17}")

MAX_MILEAGE_KM = 3_000_000
EARLIEST_YEAR = 1900

EDITABLE = (
    "title", "plate", "year", "mileage", "vin", "model_id",
    "oil_interval_km", "oil_interval_months", "osago_until", "inspection_until",
)
# Границы здравого смысла, а не правила сервиса: интервал в 50 км или в
# 10 лет — опечатка, и напоминание с ней было бы бессмысленным.
OIL_INTERVAL_KM = (1000, 50000)
OIL_INTERVAL_MONTHS = (1, 36)


def normalize_plate(raw: str) -> str:
    """«а 123 вс 74» и «A123BC74» — один номер: «А123ВС74».

    Номер с буквами вне русского набора (иностранный, транзитный) не
    трогаем, кроме регистра и пробелов: перевод в кириллицу его бы испортил.
    """
    value = re.sub(r"[\s\-]", "", raw or "").upper()
    letters = {ch for ch in value if ch.isalpha()}
    if letters and letters <= set(_PLATE_LETTERS_LAT + _PLATE_LETTERS_CYR):
        value = value.translate(_LAT_TO_CYR)
    return value[:16]


def normalize_vin(raw: str) -> str:
    value = re.sub(r"\s", "", raw or "").upper().translate(_CYR_TO_LAT)
    if value and not _VIN_RE.fullmatch(value):
        raise ValidationError(
            "VIN — 17 латинских букв и цифр, без I, O и Q", code="car_vin_invalid"
        )
    return value


def _clean(fields: dict) -> dict:
    """Привести и проверить то, что пришло от клиента или мастера."""
    data = {key: value for key, value in fields.items() if key in EDITABLE}

    if "title" in data:
        data["title"] = " ".join((data["title"] or "").split())[:120]
    if "plate" in data:
        data["plate"] = normalize_plate(data["plate"])
    if "vin" in data:
        data["vin"] = normalize_vin(data["vin"])
    if data.get("year") is not None:
        year = int(data["year"])
        if not EARLIEST_YEAR <= year <= date.today().year + 1:
            raise ValidationError("Проверьте год выпуска", code="car_year_invalid")
    if data.get("mileage") is not None:
        mileage = int(data["mileage"])
        if not 0 <= mileage <= MAX_MILEAGE_KM:
            raise ValidationError("Проверьте пробег", code="car_mileage_invalid")
    if data.get("oil_interval_km") is not None:
        low, high = OIL_INTERVAL_KM
        if not low <= int(data["oil_interval_km"]) <= high:
            raise ValidationError(
                f"Интервал замены — от {low} до {high} км", code="car_oil_interval_invalid"
            )
    if data.get("oil_interval_months") is not None:
        low, high = OIL_INTERVAL_MONTHS
        if not low <= int(data["oil_interval_months"]) <= high:
            raise ValidationError(
                f"Интервал замены — от {low} до {high} месяцев", code="car_oil_interval_invalid"
            )
    for key in ("osago_until", "inspection_until"):
        if data.get(key) is not None and not date(2000, 1, 1) <= data[key] <= date(2100, 1, 1):
            raise ValidationError("Проверьте дату", code="car_date_invalid")

    model_id = data.pop("model_id", None)
    if model_id:
        model = CarModel.objects.select_related("make").filter(pk=model_id).first()
        if model is None:
            raise ValidationError(
                "Такой модели нет в справочнике", code="car_model_unknown"
            )
        data["model"] = model
        data["make"] = model.make
        if not data.get("title"):
            data["title"] = str(model)
    return data


def _lock_owner(user) -> None:
    """Сериализовать изменения автомобилей одного клиента."""
    get_user_model().objects.select_for_update().filter(pk=user.pk).first()


def list_cars(user):
    return Car.objects.active().filter(user=user).select_related("make", "model")


def get_car(user, car_id) -> Car:
    """Свой живой автомобиль. Чужой и удалённый — одинаково «не найден»."""
    try:
        return list_cars(user).get(pk=car_id)
    except (Car.DoesNotExist, DjangoValidationError, ValueError, TypeError) as exc:
        raise NotFoundError("Автомобиль не найден", code="car_not_found") from exc


def primary_car(user) -> Car | None:
    return list_cars(user).filter(is_primary=True).first()


def _set_primary(user, car: Car) -> None:
    # Сначала снять отметку со всех, потом поставить одному — иначе на
    # мгновение основных двое, и частичный уникальный индекс откажет.
    Car.objects.active().filter(user=user, is_primary=True).exclude(pk=car.pk).update(
        is_primary=False
    )
    if not car.is_primary:
        car.is_primary = True
        car.save(update_fields=["is_primary", "updated_at"])


@transaction.atomic
def create_car(user, *, make_primary: bool = False, **fields) -> Car:
    _lock_owner(user)
    data = _clean(fields)
    if not (data.get("title") or data.get("plate")):
        raise ValidationError("Укажите марку или госномер", code="car_empty")

    active = Car.objects.active().filter(user=user)
    limit = settings.GARAGE["MAX_CARS"]
    if active.count() >= limit:
        raise ConflictError(
            f"Можно добавить не больше {limit} автомобилей", code="car_limit"
        )

    # Первая машина — основная без вопросов: записи нужно что-то подставить.
    first = not active.exists()
    car = Car.objects.create(user=user, is_primary=first, **data)
    if make_primary and not first:
        _set_primary(user, car)
    return car


@transaction.atomic
def update_car(user, car_id, *, make_primary: bool = False, **fields) -> Car:
    _lock_owner(user)
    car = get_car(user, car_id)
    data = _clean(fields)
    for key, value in data.items():
        setattr(car, key, value)
    if not (car.title or car.plate):
        raise ValidationError("Укажите марку или госномер", code="car_empty")
    if data:
        car.save(update_fields=[*data.keys(), "updated_at"])
    if make_primary:
        _set_primary(user, car)
    return car


@transaction.atomic
def set_primary(user, car_id) -> Car:
    _lock_owner(user)
    car = get_car(user, car_id)
    _set_primary(user, car)
    return car


@transaction.atomic
def archive_car(user, car_id) -> None:
    """Удалить из гаража. Записи и их снимки остаются как были.

    Удалили основной — основным становится последний добавленный из
    оставшихся: запись должна что-то подставить, а гадать клиенту не надо.
    """
    _lock_owner(user)
    car = get_car(user, car_id)
    was_primary = car.is_primary
    car.archived_at = timezone.now()
    car.is_primary = False
    car.save(update_fields=["archived_at", "is_primary", "updated_at"])
    if was_primary:
        successor = Car.objects.active().filter(user=user).order_by("-created_at").first()
        if successor:
            _set_primary(user, successor)


def car_for_booking(user, car_id=None) -> Car | None:
    """Какой автомобиль записать: выбранный клиентом или основной."""
    if car_id:
        return get_car(user, car_id)
    return primary_car(user)


@transaction.atomic
def match_or_add(user, *, title: str = "", plate: str = "") -> Car | None:
    """Машина, которую назвал мастер: найти среди машин клиента или добавить.

    Существующие машины не переписываются — клиент мог поправить их сам, а
    мастер со слов по телефону легко ошибётся. Совпадение ищется по номеру,
    а без номера — по названию. Ничего не назвали — основной автомобиль.
    """
    _lock_owner(user)
    title = " ".join((title or "").split())
    plate = normalize_plate(plate)
    cars = Car.objects.active().filter(user=user)

    if plate:
        found = cars.filter(plate=plate).first()
        if found:
            if title and not found.title:
                found.title = title[:120]
                found.save(update_fields=["title", "updated_at"])
            return found
    elif title:
        found = cars.filter(title__iexact=title).first()
        if found:
            return found
    else:
        return cars.filter(is_primary=True).first()

    if cars.count() >= settings.GARAGE["MAX_CARS"]:
        # Мастера у стойки лимит не останавливает: запись важнее гаража,
        # машина останется в снимке записи.
        return None
    return Car.objects.create(
        user=user, title=title[:120], plate=plate, is_primary=not cars.exists()
    )


@transaction.atomic
def update_primary_from_profile(
    user, *, title: str | None = None, plate: str | None = None
) -> None:
    """Старые сборки приложений правят машину через профиль (`car_model`,
    `car_plate`). Теперь это основной автомобиль: его и правим, а если
    машин ещё нет — заводим первую."""
    if title is None and plate is None:
        return
    _lock_owner(user)
    fields = {}
    if title is not None:
        fields["title"] = title
    if plate is not None:
        fields["plate"] = plate
    car = primary_car(user)
    if car is None:
        data = _clean(fields)
        if data.get("title") or data.get("plate"):
            Car.objects.create(user=user, is_primary=True, **data)
        return
    data = _clean(fields)
    for key, value in data.items():
        setattr(car, key, value)
    car.save(update_fields=[*data.keys(), "updated_at"])


def snapshot(car: Car | None) -> tuple[str, str]:
    """Что записать в снимок брони: марка и номер на момент записи."""
    if car is None:
        return "", ""
    return car.title, car.plate
