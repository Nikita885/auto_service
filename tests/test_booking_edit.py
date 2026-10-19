"""Правка записи мастером после звонка: услуга, время, машина, комментарий."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.booking.constants import BookingStatus
from apps.booking.models import Booking, BookingStatusLog, generate_booking_code
from apps.booking.services import booking as booking_service
from apps.booking.services import draft as draft_service
from apps.catalog.models import Service, ServiceCategory
from apps.garage.models import Car
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db(transaction=True)

EDITED = "Правка мастером: "


def edit_url(booking):
    return reverse("v1:master:master-booking-edit", args=[booking.pk])


def edit(api, booking, **body):
    return api.post(edit_url(booking), body, format="json")


def edits(booking):
    return list(
        BookingStatusLog.objects.filter(booking=booking, comment__startswith=EDITED)
    )


@pytest.fixture
def wash(point):
    """Услуга другой категории, без ограничения по количеству."""
    category = ServiceCategory.objects.create(
        service_point=point, name="Мойка", journal_kind="wash", allow_on_site=False
    )
    return Service.objects.create(category=category, name="Мойка кузова", price=Decimal("600"))


@pytest.fixture
def next_slot(point, free_slot):
    """Следующий слот после записи — свободный на той же точке."""
    return free_slot.start_at + timedelta(minutes=point.slot_minutes)


# ------------------------------------------------------------------ услуга
def test_service_in_the_same_category_recalculates_the_snapshot(
    auth, master_user, booking, category
):
    pricier = Service.objects.create(
        category=category, name="Mobil 1 5W-30", price=Decimal("5600"),
        material_price=Decimal("4500"), is_limited=True, quantity=2,
    )
    notifications = Notification.objects.count()

    response = edit(auth(master_user), booking, service=str(pricier.pk))

    assert response.status_code == 200, response.content
    booking.refresh_from_db()
    assert booking.service_title == "Mobil 1 5W-30"
    assert (booking.total_price, booking.material_price, booking.work_price) == (
        Decimal("5600"), Decimal("4500"), Decimal("1100"),
    )
    assert [item.title for item in booking.items.all()] == ["Mobil 1 5W-30"]
    [row] = edits(booking)
    assert row.actor == master_user
    assert "Mobil 1 5W-30" in row.comment and "было: " in row.comment
    # История — в ответе, клиенту SMS не уходит.
    assert response.json()["status_logs"][0]["comment"] == row.comment
    assert Notification.objects.count() == notifications


def test_service_from_another_category_moves_the_booking_there(
    auth, master_user, booking, wash
):
    response = edit(auth(master_user), booking, service=str(wash.pk))

    assert response.status_code == 200, response.content
    booking.refresh_from_db()
    assert booking.service_category_id == wash.category_id
    assert booking.category_title == "Мойка"
    assert booking.total_price == Decimal("600")
    assert response.json()["category_title"] == "Мойка"


def test_on_site_booking_gets_its_service_and_leaves_the_queue(
    auth, master_user, client_user, point, category, service, free_slot
):
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_category(client_user, draft.pk, category.pk)
    draft_service.select_service(client_user, draft.pk, on_site=True)
    draft_service.select_slot(client_user, draft.pk, free_slot.start_at)
    on_site = draft_service.confirm(client_user, draft.pk)

    body = edit(auth(master_user), on_site, service=str(service.pk)).json()

    assert body["needs_service"] is False
    assert body["service_title"] == service.name


def test_out_of_stock_service_changes_nothing(auth, master_user, booking, category, next_slot):
    """Одна транзакция: время не переедет, если услуга не встала."""
    empty = Service.objects.create(
        category=category, name="Закончилось", price=Decimal("1000"), is_limited=True, quantity=0
    )

    response = edit(
        auth(master_user), booking, service=str(empty.pk), start_at=next_slot.isoformat()
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "service_out_of_stock"
    old_start = booking.start_at
    booking.refresh_from_db()
    assert booking.start_at == old_start
    assert edits(booking) == []


def test_same_service_is_not_a_change(auth, master_user, booking, service):
    """Своя запись держит последнюю единицу — повтор не «разобрали»."""
    response = edit(auth(master_user), booking, service=str(service.pk))

    assert response.status_code == 200, response.content
    assert edits(booking) == []


# ------------------------------------------------------------------- время
def test_time_moves_to_a_free_slot_and_the_reminder_is_reset(
    auth, master_user, booking, next_slot
):
    Booking.objects.filter(pk=booking.pk).update(reminder_sent_at=timezone.now())
    notifications = Notification.objects.count()

    response = edit(auth(master_user), booking, start_at=next_slot.isoformat())

    assert response.status_code == 200, response.content
    booking.refresh_from_db()
    assert booking.start_at == next_slot
    assert booking.end_at == next_slot + timedelta(minutes=30)
    assert booking.reminder_sent_at is None
    [row] = edits(booking)
    assert "время" in row.comment
    assert Notification.objects.count() == notifications


def test_taken_slot_is_refused(auth, master_user, booking, other_user, point, next_slot):
    _other_booking(other_user, point, next_slot)

    response = edit(auth(master_user), booking, start_at=next_slot.isoformat())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slot_taken"


def test_client_cannot_be_in_two_places_at_once(
    auth, master_user, booking, client_user, second_point, next_slot
):
    _other_booking(client_user, second_point, next_slot)

    response = edit(auth(master_user), booking, start_at=next_slot.isoformat())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_booking"


def test_past_time_is_refused(auth, master_user, booking, point):
    past = timezone.now().replace(second=0, microsecond=0) - timedelta(hours=2)
    past = past.replace(minute=0)

    response = edit(auth(master_user), booking, start_at=past.isoformat())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "slot_too_soon"


def test_time_of_a_booking_in_work_is_fixed(auth, master_user, booking, next_slot):
    booking_service.start_work(master_user, booking.pk)

    response = edit(auth(master_user), booking, start_at=next_slot.isoformat())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "booking_not_pending"


def test_same_time_is_not_a_change(auth, master_user, booking):
    response = edit(auth(master_user), booking, start_at=booking.start_at.isoformat())

    assert response.status_code == 200, response.content
    assert edits(booking) == []


# ------------------------------------------------------- машина и комментарий
def test_car_of_the_client_from_the_garage(auth, master_user, booking, client_user):
    second = Car.objects.create(user=client_user, title="Lada Vesta", plate="О777ОО74")

    response = edit(auth(master_user), booking, car_id=str(second.pk))

    assert response.status_code == 200, response.content
    booking.refresh_from_db()
    assert (booking.car_id, booking.car_model, booking.car_plate) == (
        second.pk, "Lada Vesta", "О777ОО74",
    )
    [row] = edits(booking)
    assert "машина: Lada Vesta О777ОО74 (было: Kia Rio А123ВС77)" in row.comment


def test_named_car_is_added_to_the_garage(auth, master_user, booking, client_user):
    response = edit(auth(master_user), booking, car_model="Skoda Octavia", car_plate="в456ор99")

    assert response.status_code == 200, response.content
    booking.refresh_from_db()
    assert booking.car_model == "Skoda Octavia"
    assert booking.car.user == client_user
    assert Car.objects.filter(user=client_user).count() == 2


def test_foreign_car_is_not_found(auth, master_user, booking, other_user):
    foreign = Car.objects.create(user=other_user, title="Чужая", plate="Е001ЕЕ77")

    response = edit(auth(master_user), booking, car_id=str(foreign.pk))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "car_not_found"


def test_car_needs_a_name_or_a_plate(auth, master_user, booking):
    response = edit(auth(master_user), booking, car_model="", car_plate="")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "car_required"


def test_comment_is_set_and_cleared(auth, master_user, booking):
    api = auth(master_user)

    edit(api, booking, comment="  Приедет на 10 минут позже  ")
    booking.refresh_from_db()
    assert booking.client_comment == "Приедет на 10 минут позже"

    edit(api, booking, comment="")
    booking.refresh_from_db()
    assert booking.client_comment == ""
    assert [row.comment for row in reversed(edits(booking))] == [
        EDITED + "комментарий изменён",
        EDITED + "комментарий стёрт",
    ]


def test_everything_at_once_is_one_history_row(auth, master_user, booking, wash, next_slot):
    response = edit(
        auth(master_user), booking,
        service=str(wash.pk), start_at=next_slot.isoformat(), comment="Мойка вместо масла",
    )

    assert response.status_code == 200, response.content
    [row] = edits(booking)
    assert "время" in row.comment and "услуга" in row.comment and "комментарий" in row.comment


# ------------------------------------------------------------------ запреты
def test_empty_request_is_refused(auth, master_user, booking):
    response = edit(auth(master_user), booking)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "edit_empty"


def test_car_id_and_named_car_together_are_refused(auth, master_user, booking, client_car):
    response = edit(auth(master_user), booking, car_id=str(client_car.pk), car_model="Kia")

    assert response.status_code == 400


def test_finished_booking_is_not_edited(auth, master_user, booking):
    booking_service.cancel_by_master(master_user, booking.pk, reason="Сломался подъёмник")

    response = edit(auth(master_user), booking, comment="поздно")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "booking_final"


def test_master_of_another_point_and_client_cannot_edit(
    auth, master_user, client_user, second_point, booking
):
    master_user.service_points.add(second_point)

    assert edit(auth(master_user), booking, comment="x").status_code == 403
    assert edit(auth(client_user), booking, comment="x").status_code == 403


def _other_booking(user, point, start_at):
    return Booking.objects.create(
        code=generate_booking_code(),
        user=user,
        service_point=point,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
        status=BookingStatus.PENDING,
        client_name=user.full_name,
        client_phone=user.phone,
        category_title="Замена масла",
        service_title="Shell",
        oil_title="Shell",
        oil_price=Decimal(0),
        work_price=Decimal(0),
        total_price=Decimal(0),
    )
