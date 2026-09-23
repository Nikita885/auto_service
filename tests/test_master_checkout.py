"""Расчёт у мастера: списание баллов по желанию клиента и масла с сайта."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.booking.constants import BookingStatus
from apps.booking.services import draft as draft_service
from apps.catalog.models import Oil, OilStock
from apps.referral.constants import MatrixPosition, PointsKind
from apps.referral.models import LegCredit, PointsEntry, ReferralNode
from apps.referral.services import tree as tree_service

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def booking(client_user, point, stock, free_slot):
    """Запись на Shell за 3900 + 900 = 4800 ₽. Потолок баллов — 2400."""
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_oil(client_user, draft.pk, stock.oil_id)
    draft_service.select_slot(client_user, draft.pk, free_slot.start_at)
    return draft_service.confirm(client_user, draft.pk)


@pytest.fixture
def client_points(client_user):
    def _give(amount: str) -> ReferralNode:
        node = tree_service.ensure_node(client_user)
        ReferralNode.objects.filter(pk=node.pk).update(balance=Decimal(amount))
        node.refresh_from_db()
        return node

    return _give


def url(name, *args):
    return reverse(f"v1:master:master-booking-{name}", args=args)


def oil_url(name, *args):
    return reverse(f"v1:master:master-oil-{name}", args=args)


# ------------------------------------------------------- баллы при расчёте
def test_quote_shows_balance_and_cap(auth, master_user, booking, client_points):
    client_points("3000")

    body = auth(master_user).get(url("points", booking.pk)).json()

    assert body["balance"] == "3000.00"
    assert body["limit"] == "2400.00"      # 50 % от 4800
    assert body["max_spend"] == "2400.00"  # меньшее из баланса и потолка


def test_quote_for_client_without_points(auth, master_user, booking):
    body = auth(master_user).get(url("points", booking.pk)).json()

    assert body["balance"] == "0.00"
    assert body["max_spend"] == "0.00"


def test_complete_with_points(auth, master_user, booking, client_points):
    node = client_points("3000")

    response = auth(master_user).post(
        url("complete", booking.pk), {"points": "1000"}, format="json"
    )

    assert response.status_code == 200, response.data
    assert response.data["status"] == BookingStatus.COMPLETED
    assert response.data["points_spent"] == "1000.00"
    assert response.data["paid_amount"] == "3800.00"
    node.refresh_from_db()
    assert node.balance == Decimal("2000.00")
    spend = PointsEntry.objects.get(kind=PointsKind.SPEND)
    assert spend.amount == Decimal("-1000.00")
    assert spend.booking_id == booking.pk


def test_complete_without_points_is_unchanged(auth, master_user, booking, stock):
    response = auth(master_user).post(url("complete", booking.pk), {}, format="json")

    assert response.status_code == 200
    assert response.data["points_spent"] == "0.00"
    stock.refresh_from_db()
    assert stock.quantity == 0  # канистра списана как раньше


def test_points_above_cap_roll_everything_back(auth, master_user, booking, client_points, stock):
    """Ошибка в расчёте не должна оставить запись завершённой, а полку — пустой."""
    node = client_points("5000")

    response = auth(master_user).post(
        url("complete", booking.pk), {"points": "2500"}, format="json"
    )

    assert response.status_code == 409
    assert response.data["error"]["code"] == "points_limit_exceeded"
    booking.refresh_from_db()
    node.refresh_from_db()
    stock.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert node.balance == Decimal("5000.00")
    assert stock.quantity == 1


def test_points_above_balance_are_refused(auth, master_user, booking, client_points):
    client_points("100")

    response = auth(master_user).post(url("complete", booking.pk), {"points": "500"}, format="json")

    assert response.status_code == 409
    assert response.data["error"]["code"] == "not_enough_points"


def test_completed_booking_cannot_spend_points_twice(auth, master_user, booking, client_points):
    client_points("3000")
    api = auth(master_user)
    api.post(url("complete", booking.pk), {"points": "500"}, format="json")

    again = api.post(url("complete", booking.pk), {"points": "500"}, format="json")

    assert again.status_code == 409
    assert PointsEntry.objects.filter(kind=PointsKind.SPEND).count() == 1


def test_completion_credits_the_sponsor_leg_from_money_paid(
    auth, master_user, booking, client_user, make_sponsor
):
    """Баллы в плечо — с заплаченного деньгами: 5 % от 4800 − 800 = 200."""
    sponsor = make_sponsor(client_user)
    ReferralNode.objects.filter(user=client_user).update(balance=Decimal("800"))

    auth(master_user).post(url("complete", booking.pk), {"points": "800"}, format="json")

    credit = LegCredit.objects.get(node=sponsor)
    assert credit.side == MatrixPosition.LEFT
    assert credit.amount == Decimal("200.00")


@pytest.fixture
def make_sponsor(db):
    from apps.accounts.models import User

    def _make(client):
        sponsor_user = User.objects.create_user(phone="+79009990000", full_name="Спонсор")
        sponsor = tree_service.ensure_node(sponsor_user)
        tree_service.attach(client, sponsor.code)
        return sponsor

    return _make


# ------------------------------------------------------------ масла
NEW_OIL = {
    "brand": "Mobil",
    "name": "Super 3000",
    "viscosity": "5W-40",
    "oil_type": "synthetic",
    "volume_liters": "4.0",
    "price": "3500",
    "work_price": "900",
}


def test_master_adds_oil_with_stock(auth, master_user, point):
    response = auth(master_user).post(
        oil_url("list"),
        {**NEW_OIL, "initial_stock": [{"service_point": str(point.pk), "quantity": 6}]},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["title"] == "Mobil Super 3000 5W-40, 4.0 л"
    assert response.data["stock"] == {str(point.pk): 6}
    assert OilStock.objects.get(oil__brand="Mobil", service_point=point).quantity == 6


def test_duplicate_oil_is_refused(auth, master_user, point):
    api = auth(master_user)
    api.post(oil_url("list"), NEW_OIL, format="json")

    again = api.post(oil_url("list"), NEW_OIL, format="json")

    assert again.status_code == 409
    assert again.data["error"]["code"] == "oil_exists"
    assert Oil.objects.filter(brand="Mobil").count() == 1


def test_catalog_lists_points_and_stock(auth, master_user, point, stock):
    body = auth(master_user).get(oil_url("list")).json()

    assert [p["id"] for p in body["points"]] == [str(point.pk)]
    row = next(o for o in body["oils"] if o["id"] == str(stock.oil_id))
    assert row["stock"] == {str(point.pk): 1}


def test_master_sets_stock_and_price(auth, master_user, point, stock):
    api = auth(master_user)

    counted = api.post(
        oil_url("stock", stock.oil_id), {"service_point": str(point.pk), "quantity": 12},
        format="json",
    )
    priced = api.patch(oil_url("detail", stock.oil_id), {"price": "4100"}, format="json")

    assert counted.status_code == 200
    assert priced.status_code == 200
    assert priced.data["price"] == "4100.00"
    stock.refresh_from_db()
    assert stock.quantity == 12


def test_master_cannot_touch_other_points_stock(auth, master_user, point, second_point, stock):
    master_user.service_points.add(second_point)

    response = auth(master_user).post(
        oil_url("stock", stock.oil_id), {"service_point": str(point.pk), "quantity": 99},
        format="json",
    )

    assert response.status_code == 403
    assert response.data["error"]["code"] == "point_not_allowed"


def test_client_cannot_manage_oils(auth, client_user):
    assert auth(client_user).post(oil_url("list"), NEW_OIL, format="json").status_code == 403
    assert auth(client_user).get(oil_url("list")).status_code == 403


def test_day_revenue_counts_money_not_points(auth, master_user, booking, client_points):
    """Выручка дня — деньги в кассе: 4800 − 1000 баллами = 3800."""
    client_points("3000")
    api = auth(master_user)
    api.post(url("complete", booking.pk), {"points": "1000"}, format="json")

    local_day = booking.local_start().date().isoformat()
    summary = api.get(url("summary") + f"?date={local_day}").json()

    assert summary["revenue"] == "3800.00"
    assert summary["points_spent"] == "1000.00"
