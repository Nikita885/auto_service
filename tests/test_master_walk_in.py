"""Мастер записывает клиента сам: позвонил или приехал без записи."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.constants import UserRole
from apps.accounts.models import User
from apps.booking.constants import BookingStatus
from apps.booking.models import Booking
from apps.booking.services import draft as draft_service
from apps.booking.services import slots as slots_service
from apps.booking.services import walk_in
from apps.catalog.models import Oil, OilStock
from apps.common.exceptions import ValidationError
from apps.notifications.models import Notification, NotificationKind
from apps.referral.models import ReferralNode

pytestmark = pytest.mark.django_db(transaction=True)

NEW_PHONE = "+79005557788"

BOOKINGS_URL = reverse("v1:master:master-booking-list")


def walk_in_url(name: str) -> str:
    return reverse(f"v1:master:master-walk-in-{name}")


def payload(point, oil, slot, **extra) -> dict:
    return {
        "phone": "8 (900) 555-77-88",
        "full_name": "Сергей Звонков",
        "car_model": "Lada Vesta",
        "car_plate": "О777ОО74",
        "service_point": str(point.pk),
        "oil": str(oil.pk),
        "start_at": slot.start_at.isoformat(),
        **extra,
    }


# ----------------------------------------------------------- новый клиент
def test_new_client_is_created_and_booked(auth, master_user, point, stock, free_slot):
    resp = auth(master_user).post(
        BOOKINGS_URL, payload(point, stock.oil, free_slot), format="json"
    )

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["status"] == BookingStatus.PENDING
    assert body["client_phone"] == NEW_PHONE
    assert body["client_name"] == "Сергей Звонков"
    assert body["car_plate"] == "О777ОО74"
    # В истории видно, что запись создал мастер, а не клиент.
    assert body["status_logs"][0]["comment"] == walk_in.LOG_COMMENT
    assert body["status_logs"][0]["actor"] == master_user.display_name

    user = User.objects.get(phone=NEW_PHONE)
    assert user.role == UserRole.CLIENT
    assert not user.has_usable_password()  # входит только по SMS
    assert user.full_name == "Сергей Звонков"
    # Названная мастером машина — первый автомобиль гаража нового клиента.
    car = user.cars.get()
    assert (car.title, car.plate, car.is_primary) == ("Lada Vesta", "О777ОО74", True)
    assert Booking.objects.get(user=user).car == car
    # Узел в реферальной программе — сразу, как при регистрации.
    assert ReferralNode.objects.filter(user=user).exists()
    # То же SMS, что и при записи из приложения.
    assert Notification.objects.filter(
        user=user, kind=NotificationKind.BOOKING_CREATED
    ).exists()


def test_new_client_sees_booking_after_login(api, master_user, point, stock, free_slot):
    """Клиент входит по своему номеру — запись уже в «Моих записях»."""
    booking = walk_in.book(
        master_user, phone=NEW_PHONE, full_name="Сергей", service_point_id=point.pk,
        oil_id=stock.oil_id, start_at=free_slot.start_at,
    )

    from apps.accounts import services as accounts_services

    challenge = accounts_services.request_otp(NEW_PHONE)
    result = accounts_services.verify_otp(NEW_PHONE, challenge.debug_code)
    assert result.is_new_user is False  # аккаунт уже был, знакомство не нужно

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {result.access}")
    rows = api.get(reverse("v1:booking:booking-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert [row["code"] for row in rows] == [booking.code]


# ------------------------------------------------------ клиент уже есть
def test_existing_client_profile_is_not_overwritten(
    auth, master_user, client_user, client_car, point, stock, free_slot
):
    resp = auth(master_user).post(
        BOOKINGS_URL,
        payload(point, stock.oil, free_slot, phone=client_user.phone,
                full_name="Иван со слов", car_model="Lada Granta", car_plate="е001кх77"),
        format="json",
    )

    assert resp.status_code == 201, resp.content
    assert User.objects.filter(phone=client_user.phone).count() == 1
    client_user.refresh_from_db()
    # Своё имя клиент уже заполнил — мастер со слов его не переписывает.
    assert client_user.full_name == "Иван Тестов"
    # Машину, которой у клиента не было, мастер добавляет второй, не
    # основной; основная не тронута.
    client_car.refresh_from_db()
    assert (client_car.title, client_car.plate, client_car.is_primary) == (
        "Kia Rio", "А123ВС77", True,
    )
    added = client_user.cars.exclude(pk=client_car.pk).get()
    assert (added.title, added.plate, added.is_primary) == ("Lada Granta", "Е001КХ77", False)
    booking = Booking.objects.get(user=client_user)
    assert booking.car == added
    # В записи имя — то, что ввёл мастер: это снимок.
    assert booking.client_name == "Иван со слов"


def test_lookup_fills_known_client(auth, master_user, client_user):
    body = auth(master_user).get(
        walk_in_url("lookup") + "?phone=8 900 111-22-33"
    ).json()

    car = client_user.cars.get()
    assert body == {
        "phone": client_user.phone,
        "found": True,
        "is_client": True,
        "full_name": "Иван Тестов",
        "car_model": "Kia Rio",
        "car_plate": "А123ВС77",
        "cars": [{"id": str(car.pk), "title": "Kia Rio", "plate": "А123ВС77", "is_primary": True}],
    }


def test_lookup_unknown_phone(auth, master_user):
    body = auth(master_user).get(walk_in_url("lookup") + f"?phone={NEW_PHONE}").json()
    assert body["found"] is False
    assert body["full_name"] == ""


def test_lookup_bad_phone(auth, master_user):
    resp = auth(master_user).get(walk_in_url("lookup") + "?phone=123")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "phone_invalid"


def test_staff_phone_cannot_be_booked(auth, master_user, point, stock, free_slot):
    resp = auth(master_user).post(
        BOOKINGS_URL,
        payload(point, stock.oil, free_slot, phone=master_user.phone),
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "phone_is_staff"
    assert not Booking.objects.exists()


# ------------------------------------------------------- слот и склад
def test_taken_slot_is_rejected(auth, master_user, ready_draft, point, stock, free_slot):
    """Пост один, и его держит клиент, который записывается в приложении."""
    resp = auth(master_user).post(
        BOOKINGS_URL, payload(point, stock.oil, free_slot), format="json"
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "slot_taken"
    # Проверки идут до заведения клиента: неудачная попытка аккаунт не оставляет.
    assert not User.objects.filter(phone=NEW_PHONE).exists()


def test_booked_slot_is_rejected(auth, master_user, client_user, point, stock, free_slot):
    OilStock.objects.filter(pk=stock.pk).update(quantity=5)
    walk_in.book(
        master_user, phone=client_user.phone, full_name="Иван",
        service_point_id=point.pk, oil_id=stock.oil_id, start_at=free_slot.start_at,
    )

    resp = auth(master_user).post(
        BOOKINGS_URL, payload(point, stock.oil, free_slot), format="json"
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "slot_taken"


def test_out_of_stock_oil_is_rejected(auth, master_user, ready_draft, point, stock, free_slot):
    """Единственную канистру держит черновик клиента — на другое время тоже нет."""
    point.posts_count = 2
    point.save(update_fields=["posts_count"])

    resp = auth(master_user).post(
        BOOKINGS_URL, payload(point, stock.oil, free_slot), format="json"
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "oil_out_of_stock"


def test_oil_missing_at_point(auth, master_user, point, second_point, oil, free_slot):
    OilStock.objects.create(service_point=second_point, oil=oil, quantity=3)

    resp = auth(master_user).post(BOOKINGS_URL, payload(point, oil, free_slot), format="json")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "oil_not_available"


def test_oils_list_shows_what_is_free(auth, master_user, point, stock):
    other = Oil.objects.create(
        brand="Mobil", name="Super", viscosity="10W-40", oil_type="semi_synthetic",
        volume_liters=4, price=2500, work_price=900,
    )
    OilStock.objects.create(service_point=point, oil=other, quantity=0)

    rows = auth(master_user).get(walk_in_url("oils") + f"?service_point={point.pk}").json()
    assert [row["id"] for row in rows] == [str(stock.oil_id)]
    assert rows[0]["available_quantity"] == 1


def test_duplicate_time_for_same_client(
    auth, master_user, client_user, point, second_point, oil, free_slot
):
    OilStock.objects.create(service_point=point, oil=oil, quantity=3)
    OilStock.objects.create(service_point=second_point, oil=oil, quantity=3)
    walk_in.book(
        master_user, phone=client_user.phone, full_name="Иван",
        service_point_id=second_point.pk, oil_id=oil.pk, start_at=free_slot.start_at,
    )

    resp = auth(master_user).post(
        BOOKINGS_URL, payload(point, oil, free_slot, phone=client_user.phone), format="json"
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "duplicate_booking"


# ------------------------------------------------------------ живая очередь
def _slot_tomorrow_at(point, hour: int) -> datetime:
    day = timezone.now().astimezone(point.tz).date() + timedelta(days=1)
    return point.local_datetime(day, time(hour, 0)).astimezone(UTC)


def test_master_can_book_slot_that_already_started(master_user, point, stock):
    """Приехал без записи в 12:10 — мастер ставит его в слот 12:00, если пост свободен."""
    slot = _slot_tomorrow_at(point, 12)

    with freeze_time(slot + timedelta(minutes=10)):
        with pytest.raises(ValidationError) as err:
            slots_service.validate_slot(point, slot)  # клиенту из приложения — нельзя
        assert err.value.code == "slot_too_soon"

        day = slot.astimezone(point.tz).date()
        walk_in_starts = [s.start_at for s in slots_service.build_slots(point, day, walk_in=True)]
        assert walk_in_starts[0] == slot

        booking = walk_in.book(
            master_user, phone=NEW_PHONE, full_name="Живая очередь",
            service_point_id=point.pk, oil_id=stock.oil_id, start_at=slot,
        )
    assert booking.start_at == slot


def test_master_cannot_book_finished_slot(auth, master_user, point, stock):
    slot = _slot_tomorrow_at(point, 12)

    with freeze_time(slot + timedelta(minutes=31)):
        resp = auth(master_user).post(
            BOOKINGS_URL,
            {
                "phone": NEW_PHONE, "full_name": "Опоздал", "service_point": str(point.pk),
                "oil": str(stock.oil_id), "start_at": slot.isoformat(),
            },
            format="json",
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "slot_too_soon"


# ------------------------------------------------------------------ права
def test_foreign_point_is_forbidden(auth, master_user, point, second_point, stock, free_slot):
    master_user.service_points.set([second_point])
    api = auth(master_user)

    resp = api.post(BOOKINGS_URL, payload(point, stock.oil, free_slot), format="json")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "point_not_allowed"

    resp = api.get(walk_in_url("slots") + f"?service_point={point.pk}&date=2030-01-01")
    assert resp.status_code == 403
    assert not User.objects.filter(phone=NEW_PHONE).exists()


def test_client_cannot_book_for_others(auth, client_user, point, stock, free_slot):
    resp = auth(client_user).post(
        BOOKINGS_URL, payload(point, stock.oil, free_slot), format="json"
    )
    assert resp.status_code == 403
    assert not Booking.objects.exists()


# ------------------------------------------------------------------ гонка
def test_two_masters_race_for_last_post(master_user, point, stock, free_slot):
    """Два мастера одновременно записывают двоих на последний пост.

    Точка берётся под блокировку, второй ждёт и видит занятый слот. На
    SQLite select_for_update не работает — тест имеет смысл на PostgreSQL.
    """
    import threading

    from django.db import connection

    if connection.vendor != "postgresql":
        pytest.skip("гонку ловит только PostgreSQL")

    OilStock.objects.filter(pk=stock.pk).update(quantity=5)
    second_master = User.objects.create_master(phone="+79000000002")
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def run(master, phone):
        try:
            barrier.wait()
            walk_in.book(
                master, phone=phone, full_name="Гонка", service_point_id=point.pk,
                oil_id=stock.oil_id, start_at=free_slot.start_at,
            )
            result = "ok"
        except Exception as exc:  # noqa: BLE001 — в потоке исключение иначе теряется
            result = getattr(exc, "code", repr(exc))
        finally:
            connection.close()
        with lock:
            outcomes.append(result)

    threads = [
        threading.Thread(target=run, args=(master_user, "+79005550001")),
        threading.Thread(target=run, args=(second_master, "+79005550002")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["ok", "slot_taken"]
    assert Booking.objects.filter(start_at=free_slot.start_at).count() == 1


def test_draft_confirm_still_logs_client(client_user, ready_draft):
    """Общий конец записи не перепутал автора у записи из приложения."""
    booking = draft_service.confirm(client_user, ready_draft.pk)
    log = booking.status_logs.get()
    assert (log.actor_id, log.comment) == (client_user.pk, "Запись создана клиентом")
