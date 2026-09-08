"""Метрики администратора: доступ, подсчёты, воронка и фильтры."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.booking.constants import BookingStatus, DraftStep
from apps.booking.models import Booking, BookingDraft, generate_booking_code

pytestmark = pytest.mark.django_db(transaction=True)

URL = reverse("v1:master:metrics")


@pytest.fixture
def admin_user(db) -> User:
    return User.objects.create_superuser(phone="+79000000000", password="admin12345")


def make_booking(user, point, oil, *, status, hours_ago=2, price="1000", work="500"):
    """Запись напрямую через ORM: метрики читают базу, а не проходят сценарий."""
    start = timezone.now() - timedelta(hours=hours_ago)
    return Booking.objects.create(
        code=generate_booking_code(),
        user=user,
        service_point=point,
        oil=oil,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        status=status,
        client_name=user.full_name,
        client_phone=user.phone,
        oil_title=str(oil),
        oil_price=Decimal(price),
        work_price=Decimal(work),
        total_price=Decimal(price) + Decimal(work),
    )


# ---------------------------------------------------------------- доступ
def test_client_cannot_open_metrics(auth, client_user):
    response = auth(client_user).get(URL)

    assert response.status_code == 403


def test_master_cannot_open_metrics(auth, master_user):
    """Сводная аналитика по сети — не инструмент мастера у подъёмника."""
    response = auth(master_user).get(URL)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_admin_opens_metrics(auth, admin_user):
    response = auth(admin_user).get(URL)

    assert response.status_code == 200
    assert response.json()["period"]["days"] == 30


# ---------------------------------------------------------------- цифры
def test_revenue_counts_only_completed(auth, admin_user, client_user, point, oil):
    make_booking(client_user, point, oil, status=BookingStatus.COMPLETED)
    make_booking(client_user, point, oil, status=BookingStatus.COMPLETED, hours_ago=3)
    make_booking(client_user, point, oil, status=BookingStatus.CANCELLED_BY_CLIENT, hours_ago=4)

    totals = auth(admin_user).get(URL).json()["totals"]

    assert totals["total"] == 3
    assert totals["completed"] == 2
    assert totals["cancelled"] == 1
    # Отменённая запись денег не приносит: 2 × 1500.
    assert Decimal(totals["revenue"]) == Decimal("3000.00")
    assert Decimal(totals["avg_check"]) == Decimal("1500.00")
    assert Decimal(totals["oil_revenue"]) == Decimal("2000.00")
    assert totals["cancel_rate"] == pytest.approx(33.3)


def test_empty_period_gives_zeros_not_errors(auth, admin_user):
    """Пустая сеть — обычное состояние на старте, деления на ноль быть не должно."""
    body = auth(admin_user).get(URL).json()

    assert body["totals"]["total"] == 0
    assert Decimal(body["totals"]["revenue"]) == Decimal("0.00")
    assert body["totals"]["cancel_rate"] == 0.0
    assert body["funnel"]["conversion"] == 0.0


def test_by_day_covers_every_day_of_period(auth, admin_user):
    body = auth(admin_user).get(URL + "?date_from=2026-01-01&date_to=2026-01-05").json()

    assert [row["date"] for row in body["by_day"]] == [
        "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05",
    ]
    assert body["period"]["days"] == 5


# --------------------------------------------------------------- воронка
def test_funnel_counts_depth_by_filled_fields(auth, admin_user, client_user, point, oil):
    """Шаг закрытого черновика перезаписан на `expired`, глубину даёт заполненность."""
    BookingDraft.objects.create(
        user=client_user,
        step=DraftStep.EXPIRED,
        is_open=False,
        close_reason="expired",
        service_point=point,
        oil=oil,
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    BookingDraft.objects.create(
        user=client_user,
        step=DraftStep.EXPIRED,
        is_open=False,
        close_reason="expired",
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    funnel = auth(admin_user).get(URL).json()["funnel"]

    assert funnel["started"] == 2
    assert funnel["point_selected"] == 1
    assert funnel["oil_selected"] == 1
    assert funnel["slot_selected"] == 0
    assert funnel["expired"] == 2
    assert funnel["conversion"] == 0.0


def test_confirmed_draft_raises_conversion(auth, admin_user, client_user, ready_draft):
    from apps.booking.services import draft as draft_service

    draft_service.confirm(client_user, ready_draft.pk)

    funnel = auth(admin_user).get(URL).json()["funnel"]

    assert funnel["confirmed"] == 1
    assert funnel["conversion"] == 100.0


# --------------------------------------------------------------- фильтры
def test_point_filter_narrows_numbers(auth, admin_user, client_user, point, second_point, oil):
    make_booking(client_user, point, oil, status=BookingStatus.COMPLETED)
    make_booking(client_user, second_point, oil, status=BookingStatus.COMPLETED, hours_ago=3)

    body = auth(admin_user).get(URL + f"?service_point={point.pk}").json()

    assert body["totals"]["total"] == 1
    assert [row["name"] for row in body["by_point"]] == [point.name]


def test_unknown_point_gives_404(auth, admin_user):
    response = auth(admin_user).get(URL + "?service_point=00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "point_not_found"


def test_bad_date_is_rejected(auth, admin_user):
    response = auth(admin_user).get(URL + "?date_from=01.01.2026")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_date"


def test_reversed_period_is_swapped(auth, admin_user):
    """Перепутанные местами даты — ошибка пользователя, а не повод для 400."""
    body = auth(admin_user).get(URL + "?date_from=2026-01-10&date_to=2026-01-01").json()

    assert body["period"]["date_from"] == "2026-01-01"
    assert body["period"]["date_to"] == "2026-01-10"


# ----------------------------------------------------------------- склад
def test_stock_marks_low_positions(auth, admin_user, stock):
    body = auth(admin_user).get(URL).json()

    assert body["stock"]["total_quantity"] == stock.quantity
    assert body["stock"]["low_count"] == 1
    assert body["stock"]["items"][0]["is_low"] is True
