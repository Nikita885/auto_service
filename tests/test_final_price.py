"""Мастер меняет итог при расчёте: долил масла, добавил работу, уступил.

Запись — Shell за 3900 + 900 = 4800 ₽ (фикстура `booking` из
conftest). Итог хранится отдельно от снимка цены; потолок
баллов, баллы в плечи, выручка и метрики считаются от итога.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.booking.constants import BookingStatus
from apps.booking.models import BookingPriceChange
from apps.notifications.models import Notification, NotificationKind
from apps.referral.constants import PointsKind
from apps.referral.models import LegCredit, PointsEntry, ReferralNode

pytestmark = pytest.mark.django_db(transaction=True)


def url(name, *args):
    return reverse(f"v1:master:master-booking-{name}", args=args)


def complete(api, booking, **body):
    return api.post(url("complete", booking.pk), body, format="json")


# ------------------------------------------------------------- сам итог
def test_raised_total_is_stored_apart_from_booking_price(auth, master_user, booking):
    resp = complete(auth(master_user), booking, final_price="5300", reason="долили 1 л")

    assert resp.status_code == 200, resp.data
    booking.refresh_from_db()
    # Снимок цены на момент брони не тронут — по нему видно, откуда разница.
    assert booking.total_price == Decimal("4800.00")
    assert booking.final_price == Decimal("5300.00")
    assert resp.data["total_price"] == "4800.00"
    assert resp.data["final_price"] == "5300.00"
    assert resp.data["paid_amount"] == "5300.00"


def test_price_change_is_logged_with_who_when_why(auth, master_user, booking):
    complete(auth(master_user), booking, final_price="4500", reason="постоянный клиент")

    change = BookingPriceChange.objects.get(booking=booking)
    assert (change.old_price, change.new_price) == (Decimal("4800.00"), Decimal("4500.00"))
    assert change.reason == "постоянный клиент"
    assert change.actor_id == master_user.pk
    assert change.created_at is not None

    detail = auth(master_user).get(url("detail", booking.pk)).json()
    assert detail["price_changes"][0]["new_price"] == "4500.00"
    assert detail["price_changes"][0]["actor"] == master_user.display_name
    assert "итог 4500.00 вместо 4800.00" in detail["status_logs"][0]["comment"]


def test_reason_is_optional(auth, master_user, booking):
    resp = complete(auth(master_user), booking, final_price="5000")

    assert resp.status_code == 200
    assert BookingPriceChange.objects.get().reason == ""


def test_same_price_is_not_a_change(auth, master_user, booking):
    complete(auth(master_user), booking, final_price="4800.00", reason="так и было")

    booking.refresh_from_db()
    assert booking.final_price is None
    assert not BookingPriceChange.objects.exists()


@pytest.mark.parametrize("bad", ["0", "-100"])
def test_total_must_be_positive(auth, master_user, booking, bad):
    resp = complete(auth(master_user), booking, final_price=bad)

    assert resp.status_code == 400
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING


# ------------------------------------------------------------ баллы
def test_points_cap_follows_raised_total(auth, master_user, booking, client_points):
    """Потолок 50 % — от итога: при 6000 можно 3000, хотя от брони было бы 2400."""
    node = client_points("5000")

    resp = complete(auth(master_user), booking, final_price="6000", points="3000")

    assert resp.status_code == 200, resp.data
    assert resp.data["points_spent"] == "3000.00"
    assert resp.data["paid_amount"] == "3000.00"
    node.refresh_from_db()
    assert node.balance == Decimal("2000.00")


def test_points_cap_follows_lowered_total(auth, master_user, booking, client_points, stock):
    """Итог снизили до 2000 — баллами больше 1000 нельзя, и откатывается всё."""
    node = client_points("5000")

    resp = complete(auth(master_user), booking, final_price="2000", points="2400")

    assert resp.status_code == 409
    assert resp.data["error"]["code"] == "points_limit_exceeded"
    assert resp.data["error"]["details"]["limit"] == "1000.00"
    booking.refresh_from_db()
    node.refresh_from_db()
    stock.refresh_from_db()
    # Откат целиком: итог, статус, баллы, канистра и журнал правок.
    assert booking.final_price is None
    assert booking.status == BookingStatus.PENDING
    assert node.balance == Decimal("5000.00")
    assert stock.quantity == 1
    assert not BookingPriceChange.objects.exists()
    assert not PointsEntry.objects.filter(kind=PointsKind.SPEND).exists()


def test_legs_are_credited_from_money_of_final_total(
    auth, master_user, booking, client_user, make_sponsor
):
    """Баллы в плечо — 5 % от заплаченного деньгами: (5500 − 500) × 5 % = 250."""
    sponsor = make_sponsor(client_user)
    ReferralNode.objects.filter(user=client_user).update(balance=Decimal("500"))

    complete(auth(master_user), booking, final_price="5500", points="500")

    credit = LegCredit.objects.get(node=sponsor)
    assert credit.base_amount == Decimal("5000.00")
    assert credit.amount == Decimal("250.00")


def test_quote_uses_final_total_after_completion(auth, master_user, booking):
    api = auth(master_user)
    complete(api, booking, final_price="3000")

    quote = api.get(url("points", booking.pk)).json()
    assert quote["total_price"] == "3000.00"


# --------------------------------------------------------- выручка
def test_day_summary_revenue_uses_final_total(auth, master_user, booking, client_points):
    """Выручка дня — деньги в кассе от итога: 5200 − 1000 баллами = 4200."""
    client_points("3000")
    api = auth(master_user)
    complete(api, booking, final_price="5200", points="1000")

    local_day = booking.local_start().date().isoformat()
    summary = api.get(url("summary") + f"?date={local_day}").json()

    assert summary["revenue"] == "4200.00"
    assert summary["points_spent"] == "1000.00"


def test_metrics_use_final_total(auth, master_user, booking):
    admin = User.objects.create_superuser(phone="+79000000000", password="x" * 12)
    complete(auth(master_user), booking, final_price="4300", reason="уступили")

    from django.utils import timezone

    day = booking.local_start().date().isoformat()
    today = timezone.localdate().isoformat()
    period = f"?date_from={min(day, today)}&date_to={max(day, today)}"
    totals = auth(admin).get(reverse("v1:master:metrics") + period).json()["totals"]

    assert Decimal(totals["revenue"]) == Decimal("4300.00")
    assert Decimal(totals["avg_check"]) == Decimal("4300.00")
    # Масло и работа — по брони, правка — отдельной строкой: 3900 + 900 − 500.
    assert Decimal(totals["oil_revenue"]) == Decimal("3900.00")
    assert Decimal(totals["adjustments"]) == Decimal("-500.00")


# ------------------------------------------------------- клиент видит
def test_client_sees_final_total_in_my_bookings(auth, master_user, client_user, booking):
    complete(auth(master_user), booking, final_price="5100", reason="долили")

    rows = auth(client_user).get(reverse("v1:booking:booking-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    row = rows[0]
    # Свой чек клиент видит — это то, что он заплатил. Цены записи, по
    # которой видно «было 4800», клиенту не отдаём (решение заказчика).
    assert row["final_price"] == "5100.00"
    assert row["paid_amount"] == "5100.00"
    assert not {"total_price", "oil_price", "work_price", "price_changed"} & row.keys()


def test_pending_booking_shows_no_amount_to_client(auth, client_user, booking):
    rows = auth(client_user).get(reverse("v1:booking:booking-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    # До визита суммы нет вовсе — ни в интерфейсе, ни в JSON.
    assert rows[0]["final_price"] is None
    assert rows[0]["paid_amount"] is None


def test_completion_sms_names_final_total(auth, master_user, booking):
    complete(auth(master_user), booking, final_price="5100")

    sms = Notification.objects.get(kind=NotificationKind.BOOKING_COMPLETED)
    assert "5100 ₽" in sms.text


# ------------------------------------------------------------- права
def test_completed_booking_price_cannot_be_changed_again(auth, master_user, booking):
    api = auth(master_user)
    complete(api, booking, final_price="5000")

    again = complete(api, booking, final_price="1")

    assert again.status_code == 409
    assert again.data["error"]["code"] == "booking_final"
    booking.refresh_from_db()
    assert booking.final_price == Decimal("5000.00")
    assert BookingPriceChange.objects.count() == 1


def test_master_of_other_point_cannot_change_total(
    auth, master_user, booking, second_point
):
    master_user.service_points.set([second_point])

    resp = complete(auth(master_user), booking, final_price="1")

    assert resp.status_code == 403
    booking.refresh_from_db()
    assert booking.final_price is None


def test_client_cannot_complete(auth, client_user, booking):
    resp = complete(auth(client_user), booking, final_price="1")
    assert resp.status_code == 403
