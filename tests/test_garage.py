"""Гараж: автомобили клиента, выбор машины при записи, перенос из профиля.

Права: чужая машина везде «не найдена» — и в гараже, и при записи, и у
мастера в окне «Записать клиента». Удалённая машина не ломает историю.
"""

from __future__ import annotations

import threading
from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse

from apps.booking.models import Booking
from apps.booking.services import draft as draft_service
from apps.common.exceptions import NotFoundError
from apps.garage.models import Car
from apps.garage.services import cars as cars_service
from apps.garage.services.cars import normalize_plate

pytestmark = pytest.mark.django_db(transaction=True)

CARS_URL = reverse("v1:garage:car-list")


def car_url(car, name="detail"):
    return reverse(f"v1:garage:car-{name}", args=[car.pk])


# ---------------------------------------------------------------- номер
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a 123 bc 77", "А123ВС77"),  # латиница → кириллица
        ("А123ВС-777", "А123ВС777"),
        ("x001xx", "Х001ХХ"),
        ("AB 1234 D", "AB1234D"),  # D вне русского набора — номер чужой, не трогаем
        ("", ""),
    ],
)
def test_plate_is_normalized(raw, expected):
    assert normalize_plate(raw) == expected


# ------------------------------------------------------------- гараж API
def test_first_car_is_primary_second_is_not(auth, other_user):
    api = auth(other_user)
    first = api.post(CARS_URL, {"title": "Kia Rio", "plate": "a123bc77"}, format="json")
    second = api.post(CARS_URL, {"title": "Lada Vesta"}, format="json")

    assert first.status_code == 201, first.content
    assert first.json()["is_primary"] is True
    assert first.json()["plate"] == "А123ВС77"
    assert second.json()["is_primary"] is False

    rows = api.get(CARS_URL).json()
    assert [row["title"] for row in rows] == ["Kia Rio", "Lada Vesta"]  # основная первой


def test_make_primary_moves_the_flag(auth, client_user, client_car):
    other = cars_service.create_car(client_user, title="Lada Vesta")

    resp = auth(client_user).post(car_url(other, "make-primary"))

    assert resp.status_code == 200
    client_car.refresh_from_db()
    other.refresh_from_db()
    assert (client_car.is_primary, other.is_primary) == (False, True)


def test_create_with_is_primary_takes_the_flag(auth, client_user, client_car):
    resp = auth(client_user).post(
        CARS_URL, {"title": "Lada Vesta", "is_primary": True}, format="json"
    )
    assert resp.json()["is_primary"] is True
    assert Car.objects.active().filter(user=client_user, is_primary=True).count() == 1


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({}, "car_empty"),
        ({"title": "  ", "plate": ""}, "car_empty"),
        ({"title": "Kia", "year": 1800}, "car_year_invalid"),
        ({"title": "Kia", "mileage": -5}, "car_mileage_invalid"),
        ({"title": "Kia", "vin": "123"}, "car_vin_invalid"),
        ({"title": "Kia", "vin": "XTA21099O12345678"}, "car_vin_invalid"),  # буква O
    ],
)
def test_bad_car_is_rejected(auth, other_user, body, code):
    resp = auth(other_user).post(CARS_URL, body, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == code


def test_vin_typed_in_cyrillic_is_accepted(auth, other_user):
    # «ХТА» на русской раскладке — те же буквы, что XTA.
    resp = auth(other_user).post(
        CARS_URL, {"title": "Lada", "vin": "хта21099012345678"}, format="json"
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["vin"] == "XTA21099012345678"


def test_title_from_catalog_model(auth, other_user):
    from apps.catalog.models import CarMake, CarModel

    make = CarMake.objects.create(name="Kia")
    model = CarModel.objects.create(make=make, name="Rio")

    resp = auth(other_user).post(CARS_URL, {"model_id": str(model.pk)}, format="json")

    assert resp.status_code == 201, resp.content
    assert resp.json()["title"] == str(model)
    assert resp.json()["model_id"] == str(model.pk)


def test_car_limit(auth, other_user, settings):
    settings.GARAGE = {**settings.GARAGE, "MAX_CARS": 2}
    api = auth(other_user)
    api.post(CARS_URL, {"title": "A"}, format="json")
    api.post(CARS_URL, {"title": "B"}, format="json")

    resp = api.post(CARS_URL, {"title": "C"}, format="json")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "car_limit"


def test_foreign_car_is_not_found_everywhere(auth, client_user, client_car, other_user):
    api = auth(other_user)
    assert api.get(CARS_URL).json() == []
    for resp in (
        api.get(car_url(client_car)),
        api.patch(car_url(client_car), {"title": "угнали"}, format="json"),
        api.delete(car_url(client_car)),
        api.post(car_url(client_car, "make-primary")),
    ):
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "car_not_found"
    client_car.refresh_from_db()
    assert (client_car.title, client_car.archived_at) == ("Kia Rio", None)


def test_staff_has_no_garage(auth, master_user):
    assert auth(master_user).get(CARS_URL).status_code == 403


def test_deleting_primary_promotes_another(auth, client_user, client_car):
    other = cars_service.create_car(client_user, title="Lada Vesta")

    resp = auth(client_user).delete(car_url(client_car))

    assert resp.status_code == 204
    other.refresh_from_db()
    assert other.is_primary
    assert [row["id"] for row in auth(client_user).get(CARS_URL).json()] == [str(other.pk)]
    # Мягкое удаление: строка на месте, на неё ссылаются записи.
    assert Car.objects.filter(pk=client_car.pk, archived_at__isnull=False).exists()


def test_deleted_car_does_not_break_history(auth, client_user, client_car, booking):
    auth(client_user).delete(car_url(client_car))

    rows = auth(client_user).get(reverse("v1:booking:booking-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert rows[0]["car_model"] == "Kia Rio"
    assert rows[0]["car_plate"] == "А123ВС77"
    booking.refresh_from_db()
    assert booking.car_id == client_car.pk


@pytest.mark.skipif(
    connection.vendor != "postgresql", reason="блокировки строк есть только в PostgreSQL"
)
def test_parallel_first_cars_make_one_primary(other_user):
    errors: list[str] = []

    def add(title: str) -> None:
        try:
            cars_service.create_car(other_user, title=title)
        except Exception as exc:  # noqa: BLE001 — в потоке исключение иначе теряется
            errors.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=add, args=(f"Машина {n}",)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert Car.objects.filter(user=other_user).count() == 4
    assert Car.objects.filter(user=other_user, is_primary=True).count() == 1


# ------------------------------------------------------ машина при записи
def confirm_url(draft):
    return reverse("v1:booking:booking-draft-confirm", args=[draft.pk])


def test_confirm_with_chosen_car(auth, client_user, ready_draft):
    second = cars_service.create_car(client_user, title="Lada Vesta", plate="х001хх74")

    resp = auth(client_user).post(
        confirm_url(ready_draft), {"car_id": str(second.pk)}, format="json"
    )

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["car"]["id"] == str(second.pk)
    assert (body["car_model"], body["car_plate"]) == ("Lada Vesta", "Х001ХХ74")
    booking = Booking.objects.get(pk=body["id"])
    assert booking.car == second


def test_confirm_with_foreign_car_keeps_draft(auth, client_user, other_user, ready_draft):
    foreign = cars_service.create_car(other_user, title="Чужая")

    resp = auth(client_user).post(
        confirm_url(ready_draft), {"car_id": str(foreign.pk)}, format="json"
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "car_not_found"
    ready_draft.refresh_from_db()
    assert ready_draft.is_open  # можно выбрать свою и подтвердить
    assert not Booking.objects.exists()


def test_confirm_with_deleted_car_is_refused(auth, client_user, client_car, ready_draft):
    cars_service.archive_car(client_user, client_car.pk)

    resp = auth(client_user).post(
        confirm_url(ready_draft), {"car_id": str(client_car.pk)}, format="json"
    )
    assert resp.status_code == 404


def test_confirm_without_any_car(other_user, point, stock, free_slot):
    draft = draft_service.start_draft(other_user)
    draft_service.select_point(other_user, draft.pk, point.pk)
    draft_service.select_oil(other_user, draft.pk, stock.oil_id)
    draft_service.select_slot(other_user, draft.pk, free_slot.start_at)

    booking = draft_service.confirm(other_user, draft.pk)

    assert (booking.car, booking.car_model, booking.car_plate) == (None, "", "")


# --------------------------------------------------------- профиль
def test_old_profile_fields_create_first_car(auth, other_user):
    resp = auth(other_user).patch(
        reverse("v1:accounts:me"), {"car_model": "Kia Rio", "car_plate": "a123bc77"},
        format="json",
    )

    assert resp.status_code == 200
    car = Car.objects.get(user=other_user)
    assert (car.title, car.plate, car.is_primary) == ("Kia Rio", "А123ВС77", True)
    me = auth(other_user).get(reverse("v1:accounts:me")).json()
    assert (me["car_model"], me["car_plate"]) == ("Kia Rio", "А123ВС77")


# ------------------------------------------------------------- мастер
WALK_IN_URL = reverse("v1:master:master-booking-list")


def walk_in(api, point, stock, slot, **extra):
    body = {
        "phone": "+79001112233",
        "full_name": "Иван",
        "service_point": str(point.pk),
        "oil": str(stock.oil_id),
        "start_at": slot.start_at.isoformat(),
        **extra,
    }
    return api.post(WALK_IN_URL, body, format="json")


def test_master_books_chosen_car_of_client(
    auth, master_user, client_user, client_car, point, stock, free_slot
):
    second = cars_service.create_car(client_user, title="Lada Vesta")

    resp = walk_in(auth(master_user), point, stock, free_slot, car_id=str(second.pk))

    assert resp.status_code == 201, resp.content
    assert resp.json()["car_model"] == "Lada Vesta"
    assert Booking.objects.get().car == second


def test_master_cannot_book_someone_elses_car(
    auth, master_user, client_user, other_user, point, stock, free_slot
):
    foreign = cars_service.create_car(other_user, title="Чужая")

    resp = walk_in(auth(master_user), point, stock, free_slot, car_id=str(foreign.pk))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "car_not_found"
    assert not Booking.objects.exists()


def test_master_plate_in_latin_finds_existing_car(
    auth, master_user, client_user, client_car, point, stock, free_slot
):
    resp = walk_in(
        auth(master_user), point, stock, free_slot, car_model="киа", car_plate="a123bc77"
    )

    assert resp.status_code == 201, resp.content
    assert Car.objects.filter(user=client_user).count() == 1  # новой не завели
    assert Booking.objects.get().car == client_car


def test_master_search_by_latin_plate(auth, master_user, booking):
    rows = auth(master_user).get(WALK_IN_URL + "?search=a123").json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert [row["code"] for row in rows] == [booking.code]


def test_lookup_hides_staff_details(auth, master_user):
    from apps.accounts.models import User

    User.objects.create_master(phone="+79000000002", full_name="Другой мастер")
    body = auth(master_user).get(
        reverse("v1:master:master-walk-in-lookup") + "?phone=+79000000002"
    ).json()
    assert (body["is_client"], body["full_name"], body["cars"]) == (False, "", [])


def test_get_car_rejects_garbage_id(client_user):
    with pytest.raises(NotFoundError):
        cars_service.get_car(client_user, "не-uuid")


# ------------------------------------------------- миграция из профиля
BEFORE = [
    ("accounts", "0003_otp_verificahub"),
    ("booking", "0003_final_price"),
    ("garage", None),
]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    # «Приложение откачено целиком» (None) в состоянии проекта не узел графа.
    return executor.loader.project_state([t for t in targets if t[1]]).apps


def _leaves():
    return MigrationExecutor(connection).loader.graph.leaf_nodes()


def test_profile_car_migrates_to_garage_and_back():
    """Заполненная база: машина из профиля становится машиной гаража,
    записи с той же машиной привязываются, чужие снимки — нет; откат
    возвращает машину в профиль."""
    try:
        _check_migration_roundtrip()
    finally:
        _migrate(_leaves())  # следующие тесты ждут схему целиком, даже после падения


def _check_migration_roundtrip():
    from datetime import UTC, datetime, timedelta

    old = _migrate(BEFORE)
    User = old.get_model("accounts", "User")
    Booking_ = old.get_model("booking", "Booking")
    Point = old.get_model("catalog", "ServicePoint")
    Oil = old.get_model("catalog", "Oil")

    owner = User.objects.create(phone="+79001110001", car_model="Kia  Rio", car_plate="a 123 bc 77")
    User.objects.create(phone="+79001110002")  # без машины
    plate_only = User.objects.create(phone="+79001110003", car_plate="E001KX")

    point = Point.objects.create(name="Т", address="А")
    oil = Oil.objects.create(
        brand="S", name="H", viscosity="5W-30", oil_type="synthetic",
        volume_liters=Decimal("4"), price=Decimal("1"), work_price=Decimal("1"),
    )
    start = datetime(2026, 1, 10, 9, tzinfo=UTC)

    def booking(code, model, plate, shift):
        return Booking_.objects.create(
            code=code, user=owner, service_point=point, oil=oil,
            start_at=start + timedelta(days=shift), end_at=start + timedelta(days=shift, hours=1),
            client_phone=owner.phone, car_model=model, car_plate=plate, oil_title="S H",
            oil_price=1, work_price=1, total_price=2, status="completed",
        )

    same = booking("SAME01", "Kia Rio", "А123ВС77", 0)
    other = booking("OTHR01", "Lada", "Х001ХХ77", 1)

    new = _migrate(_leaves())
    Car_ = new.get_model("garage", "Car")
    NewBooking = new.get_model("booking", "Booking")

    car = Car_.objects.get(user_id=owner.pk)
    assert (car.title, car.plate, car.is_primary) == ("Kia Rio", "А123ВС77", True)
    assert Car_.objects.get(user_id=plate_only.pk).plate == "Е001КХ"
    assert Car_.objects.count() == 2
    assert NewBooking.objects.get(pk=same.pk).car_id == car.pk
    assert NewBooking.objects.get(pk=other.pk).car_id is None
    # Снимки в записях не тронуты.
    assert NewBooking.objects.get(pk=other.pk).car_plate == "Х001ХХ77"

    back = _migrate(BEFORE)
    OldUser = back.get_model("accounts", "User")
    restored = OldUser.objects.get(pk=owner.pk)
    assert (restored.car_model, restored.car_plate) == ("Kia Rio", "А123ВС77")
