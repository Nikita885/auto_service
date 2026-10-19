"""Карточка клиента у мастера: поиск по номеру в любой записи и карточка."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.booking.services import calls as calls_service

pytestmark = pytest.mark.django_db(transaction=True)

SEARCH_URL = reverse("v1:master:client-search")


def card_url(user):
    return reverse("v1:master:client-card", args=[user.pk])


def search(api, phone):
    return api.get(SEARCH_URL, {"phone": phone})


# ------------------------------------------------------------------ поиск
@pytest.mark.parametrize(
    "raw", ["+7 900 111-22-33", "8 (900) 111 22 33", "89001112233", "+79001112233", "9001112233"]
)
def test_full_number_in_any_format_finds_the_client(auth, master_user, client_user, raw):
    response = search(auth(master_user), raw)

    assert response.status_code == 200, response.content
    assert [row["id"] for row in response.json()] == [str(client_user.pk)]
    assert response.json()[0]["car"] == "Kia Rio А123ВС77"


def test_last_digits_find_by_number_ending(auth, master_user, client_user, other_user):
    rows = search(auth(master_user), "2233").json()

    assert [row["phone"] for row in rows] == [client_user.phone]


def test_too_short_input_is_refused(auth, master_user):
    response = search(auth(master_user), "23")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "phone_too_short"


def test_staff_numbers_are_not_clients(auth, master_user):
    assert search(auth(master_user), master_user.phone).json() == []


# ---------------------------------------------------------------- карточка
def test_card_shows_everything_for_the_call(
    auth, master_user, client_user, booking, client_points, make_sponsor
):
    client_points("3000")
    make_sponsor(client_user)
    calls_service.log_call(master_user, booking_id=booking.pk, outcome="no_answer", note="занято")

    body = auth(master_user).get(card_url(client_user)).json()

    assert body["client"]["full_name"] == client_user.full_name
    assert [car["title"] for car in body["cars"]] == ["Kia Rio"]
    assert [b["code"] for b in body["upcoming"]] == [booking.code]
    assert body["past"] == []
    # Баллы и сколько можно списать в ближайшую запись: 50 % от 4800.
    assert Decimal(body["points"]["balance"]) == Decimal("3000")
    assert body["points"]["next"]["booking_code"] == booking.code
    assert Decimal(body["points"]["next"]["limit"]) == Decimal("2400")
    assert Decimal(body["points"]["next"]["max_spend"]) == Decimal("2400")
    # Пригласивший — именем, номер замаскирован.
    assert body["invited_by"]["name"] == "Спонсор"
    assert "***" in body["invited_by"]["phone"]
    assert [call["note"] for call in body["calls"]] == ["занято"]


def test_card_without_bookings_and_points(auth, master_user, other_user):
    body = auth(master_user).get(card_url(other_user)).json()

    assert body["upcoming"] == [] and body["past"] == []
    assert body["points"]["next"] is None
    assert body["invited_by"] is None


def test_bookings_of_another_point_are_not_shown(
    auth, master_user, client_user, second_point, booking
):
    """Машины и баллы — клиентские, а записи и звонки — только своих точек."""
    master_user.service_points.add(second_point)

    body = auth(master_user).get(card_url(client_user)).json()

    assert body["upcoming"] == []
    assert [car["title"] for car in body["cars"]] == ["Kia Rio"]


def test_unknown_and_staff_ids_are_404(auth, master_user):
    api = auth(master_user)
    staff = User.objects.create_master(phone="+79000000009", full_name="Другой мастер")

    for target in (uuid.uuid4(), staff.pk):
        response = api.get(reverse("v1:master:client-card", args=[target]))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "client_not_found"


def test_client_cannot_search_or_open_cards(auth, client_user, other_user):
    api = auth(client_user)

    assert search(api, "2233").status_code == 403
    assert api.get(card_url(other_user)).status_code == 403


def test_master_booking_carries_the_client_id(auth, master_user, booking):
    """Из строки смены карточка открывается по id клиента."""
    url = reverse("v1:master:master-booking-detail", args=[booking.pk])

    assert auth(master_user).get(url).json()["user"] == str(booking.user_id)
