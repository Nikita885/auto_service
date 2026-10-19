"""Баллы клиента в строке смены — видны мастеру до расчёта."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.booking.constants import BookingStatus
from apps.booking.models import Booking, generate_booking_code
from apps.booking.services import booking as booking_service
from apps.referral.models import ReferralNode
from apps.referral.services import tree as tree_service

pytestmark = pytest.mark.django_db(transaction=True)

LIST_URL = reverse("v1:master:master-booking-list")


def points_of(api, booking):
    rows = api.get(LIST_URL, {"search": booking.code}).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    [row] = [row for row in rows if row["id"] == str(booking.pk)]
    return row["client_points"]


def test_balance_and_the_cap_of_this_check(auth, master_user, booking, client_points):
    """4800 ₽ — потолок 50 % = 2400; баланса хватает на весь потолок."""
    client_points("3000")

    points = points_of(auth(master_user), booking)

    assert Decimal(points["balance"]) == Decimal("3000")
    assert Decimal(points["limit"]) == Decimal("2400")
    assert Decimal(points["max_spend"]) == Decimal("2400")
    assert points["max_discount_percent"] == 50


def test_small_balance_is_the_limit(auth, master_user, booking, client_points):
    client_points("700")

    assert Decimal(points_of(auth(master_user), booking)["max_spend"]) == Decimal("700")


def test_client_without_the_program_has_zero(auth, master_user, booking):
    assert not ReferralNode.objects.filter(user=booking.user).exists()

    points = points_of(auth(master_user), booking)

    assert Decimal(points["balance"]) == 0 and Decimal(points["max_spend"]) == 0


def test_same_numbers_as_the_checkout_window(auth, master_user, booking, client_points):
    client_points("1800")
    api = auth(master_user)
    quote = api.get(reverse("v1:master:master-booking-points", args=[booking.pk])).json()

    points = points_of(api, booking)

    assert Decimal(points["max_spend"]) == Decimal(quote["max_spend"])
    assert Decimal(points["limit"]) == Decimal(quote["limit"])


def test_on_site_booking_shows_balance_without_a_check(
    auth, master_user, client_user, point, client_points, free_slot
):
    """Услугу ещё не выбрали — чека нет, списать пока нечего."""
    client_points("1500")
    on_site = _booking(client_user, point, free_slot.start_at, total="0")

    points = points_of(auth(master_user), on_site)

    assert Decimal(points["balance"]) == Decimal("1500")
    assert Decimal(points["max_spend"]) == 0


def test_closed_booking_has_no_preview(auth, master_user, booking, client_points):
    client_points("3000")
    booking_service.cancel_by_master(master_user, booking.pk, reason="Сломался подъёмник")

    assert points_of(auth(master_user), booking) is None


def test_after_checkout_the_row_shows_what_was_spent(
    auth, master_user, booking, client_points
):
    client_points("3000")
    booking_service.start_work(master_user, booking.pk)
    booking_service.complete(master_user, booking.pk, points=Decimal("1000"))

    api = auth(master_user)
    rows = api.get(LIST_URL, {"search": booking.code}).json()
    rows = rows["results"] if isinstance(rows, dict) else rows

    assert rows[0]["client_points"] is None
    assert Decimal(rows[0]["points_spent"]) == Decimal("1000")


def test_shift_list_does_not_query_per_row(auth, master_user, point, free_slot):
    """Баланс приходит тем же JOIN, что и клиент: строк больше — запросов нет."""
    api = auth(master_user)

    def count_queries():
        with CaptureQueriesContext(connection) as ctx:
            assert api.get(LIST_URL).status_code == 200
        return len(ctx)

    _client_booking("+79005550001", point, free_slot.start_at)
    one = count_queries()
    for n, minutes in ((2, 60), (3, 120)):
        _client_booking(f"+7900555000{n}", point, free_slot.start_at + timedelta(minutes=minutes))

    assert count_queries() == one


def test_client_card_bookings_carry_points(auth, master_user, client_user, booking, client_points):
    client_points("3000")

    body = auth(master_user).get(reverse("v1:master:client-card", args=[client_user.pk])).json()

    assert Decimal(body["upcoming"][0]["client_points"]["max_spend"]) == Decimal("2400")


def _client_booking(phone, point, start_at):
    user = User.objects.create_user(phone=phone, full_name="Клиент " + phone[-1])
    node = tree_service.ensure_node(user)
    ReferralNode.objects.filter(pk=node.pk).update(balance=Decimal("500"))
    return _booking(user, point, start_at, total="4800")


def _booking(user, point, start_at, *, total):
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
        service_on_site=total == "0",
        oil_title="Shell",
        oil_price=Decimal(0),
        work_price=Decimal(0),
        total_price=Decimal(total),
    )
