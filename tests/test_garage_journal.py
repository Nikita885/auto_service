"""Дневник водителя: записи, расход, напоминания, статистика и права.

Даты закреплены `freeze_time`: напоминания и периоды считаются от
«сегодня», и без этого тесты зависели бы от дня прогона.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse
from freezegun import freeze_time

from apps.booking.constants import BookingStatus
from apps.booking.models import Booking
from apps.garage.models import EntryKind, LogEntry
from apps.garage.services import cars as cars_service
from apps.garage.services import journal

pytestmark = pytest.mark.django_db(transaction=True)


def journal_url(car):
    return reverse("v1:garage:car-journal", args=[car.pk])


def summary_url(car):
    return reverse("v1:garage:car-summary", args=[car.pk])


def entry_url(entry_id):
    return reverse("v1:garage:entry-detail", args=[entry_id])


def add(car, kind, day, **extra):
    return LogEntry.objects.create(car=car, kind=kind, date=day, **extra)


def oil_of(reminders):
    return next(r for r in reminders if r.kind == "oil")


# ---------------------------------------------------------------- записи
def test_add_fuel_bumps_car_mileage(auth, client_user, client_car):
    resp = auth(client_user).post(journal_url(client_car), {
        "kind": "fuel", "liters": "40", "amount": "2600", "mileage": 84300, "full_tank": True,
    }, format="json")

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert (body["kind"], body["liters"], body["editable"]) == ("fuel", "40.00", True)
    client_car.refresh_from_db()
    assert client_car.mileage == 84300


def test_lower_mileage_does_not_rewind_car(client_user, client_car):
    cars_service.update_car(client_user, client_car.pk, mileage=90000)
    journal.add_entry(client_user, client_car.pk, kind="wash", mileage=80000, amount=Decimal(500))
    client_car.refresh_from_db()
    assert client_car.mileage == 90000


def test_fuel_needs_liters(auth, client_user, client_car):
    resp = auth(client_user).post(journal_url(client_car), {"kind": "fuel", "amount": "1000"},
                                  format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "entry_liters_required"


def test_liters_are_dropped_for_non_fuel(client_user, client_car):
    entry = journal.add_entry(client_user, client_car.pk, kind="wash", liters=Decimal(30))
    assert (entry.liters, entry.full_tank) == (None, True)


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"kind": "wash", "date": "2099-01-01"}, "entry_date_invalid"),
        ({"kind": "wash", "date": "1980-01-01"}, "entry_date_invalid"),
        ({"kind": "wash", "amount": "-5"}, "entry_amount_invalid"),
        ({"kind": "fuel", "liters": "0"}, "entry_liters_invalid"),
        ({"kind": "wash", "mileage": -1}, "car_mileage_invalid"),
    ],
)
def test_bad_entry_is_rejected(auth, client_user, client_car, body, code):
    resp = auth(client_user).post(journal_url(client_car), body, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == code


def test_unknown_kind_is_rejected(auth, client_user, client_car):
    resp = auth(client_user).post(journal_url(client_car), {"kind": "teleport"}, format="json")
    assert resp.status_code == 400


def test_edit_and_delete_own_entry(auth, client_user, client_car):
    entry = add(client_car, EntryKind.WASH, date(2026, 10, 1), amount=Decimal(500))
    api = auth(client_user)

    resp = api.patch(entry_url(entry.pk), {"amount": "700", "note": "  с  воском "}, format="json")
    assert resp.status_code == 200
    entry.refresh_from_db()
    assert (entry.amount, entry.note) == (Decimal(700), "с воском")

    assert api.delete(entry_url(entry.pk)).status_code == 204
    assert not LogEntry.objects.filter(pk=entry.pk).exists()


def test_foreign_journal_is_not_found(auth, client_user, client_car, other_user):
    entry = add(client_car, EntryKind.WASH, date(2026, 10, 1))
    api = auth(other_user)
    assert api.get(journal_url(client_car)).status_code == 404
    assert api.get(summary_url(client_car)).status_code == 404
    assert api.post(journal_url(client_car), {"kind": "wash"}, format="json").status_code == 404
    for resp in (api.patch(entry_url(entry.pk), {"amount": "1"}, format="json"),
                 api.delete(entry_url(entry.pk))):
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "entry_not_found"
    assert LogEntry.objects.filter(pk=entry.pk).exists()


def test_deleted_car_hides_its_journal(auth, client_user, client_car):
    entry = add(client_car, EntryKind.WASH, date(2026, 10, 1))
    cars_service.create_car(client_user, title="Вторая")
    cars_service.archive_car(client_user, client_car.pk)
    api = auth(client_user)
    assert api.get(journal_url(client_car)).status_code == 404
    assert api.patch(entry_url(entry.pk), {"amount": "1"}, format="json").status_code == 404


def test_staff_has_no_journal(auth, master_user, client_car):
    assert auth(master_user).get(journal_url(client_car)).status_code == 403


# ---------------------------------------------------------------- расход
def test_fuel_full_to_full():
    rows = [
        _fuel(date(2026, 9, 1), 10000, "40", full=True),   # старт отрезка
        _fuel(date(2026, 9, 5), 10200, "15", full=False),  # неполная — в отрезок
        _fuel(date(2026, 9, 9), 10500, "22", full=True),   # 37 л на 500 км
        _fuel(date(2026, 9, 15), 11000, "40", full=True),  # 40 л на 500 км
    ]
    result = journal.fuel(rows)
    assert result.last == Decimal("8.0")
    assert result.average == Decimal("7.7")  # 77 л на 1000 км
    assert result.distance == 1000


def test_fuel_needs_two_full_tanks():
    rows = [_fuel(date(2026, 9, 1), 10000, "40", full=False),
            _fuel(date(2026, 9, 5), 10300, "20", full=True)]
    assert journal.fuel(rows).average is None


def _fuel(day, km, liters, *, full):
    return journal.Item(id=str(day), kind="fuel", date=day, mileage=km, amount=None,
                        liters=Decimal(liters), full_tank=full, note="", source="manual")


# ----------------------------------------------------------- напоминания
@freeze_time("2026-10-07")
def test_oil_unknown_without_any_change(client_car):
    assert oil_of(journal.reminders(client_car, [])).status == "unknown"


@freeze_time("2026-10-07")
def test_oil_soon_by_kilometres(client_car):
    add(client_car, EntryKind.OIL, date(2026, 8, 1), mileage=50000)
    add(client_car, EntryKind.FUEL, date(2026, 10, 5), mileage=59500, liters=Decimal(30))
    oil = oil_of(journal.summary(client_car.user, client_car.pk)["reminders"])
    assert (oil.due_km, oil.left_km, oil.status) == (60000, 500, "soon")
    assert oil.due_date == date(2027, 8, 1)


@freeze_time("2026-10-07")
def test_oil_overdue_by_date_and_custom_interval(client_user, client_car):
    cars_service.update_car(client_user, client_car.pk, oil_interval_months=6)
    add(client_car, EntryKind.OIL, date(2026, 3, 1))
    oil = oil_of(journal.summary(client_user, client_car.pk)["reminders"])
    assert (oil.status, oil.due_date) == ("overdue", date(2026, 9, 1))


@freeze_time("2026-10-07")
def test_oil_change_at_our_service_counts(client_user, client_car, booking):
    """Замена у нас — последняя замена; пробег берётся с заправки рядом."""
    Booking.objects.filter(pk=booking.pk).update(status=BookingStatus.COMPLETED)
    day = booking.local_start().date()
    add(client_car, EntryKind.FUEL, day, mileage=70000, liters=Decimal(30))

    data = journal.summary(client_user, client_car.pk)
    oil = oil_of(data["reminders"])
    assert oil.last_date == day
    assert oil.due_km == 80000
    ours = [r for r in data["recent"] if r.source == "booking"]
    assert ours and ours[0].booking_code == booking.code and not ours[0].editable
    # Сумма — то, что заплачено деньгами.
    assert ours[0].amount == booking.paid_amount


@freeze_time("2026-10-07")
def test_documents(client_user, client_car):
    cars_service.update_car(client_user, client_car.pk, osago_until=date(2026, 10, 20),
                            inspection_until=date(2027, 6, 1))
    found = {r.kind: r for r in journal.summary(client_user, client_car.pk)["reminders"]}
    assert (found["osago"].status, found["osago"].left_days) == ("soon", 13)
    assert found["inspection"].status == "ok"


@pytest.mark.parametrize(
    ("today", "status", "season"),
    [
        ("2026-09-15", "soon", "winter"),     # за 16 дней до 1 октября
        ("2026-10-15", "overdue", "winter"),  # сезон начался, не поменяли
        ("2026-04-10", "soon", "summer"),     # за 10 дней до 20 апреля
        ("2026-07-01", None, None),           # между сезонами — тихо
    ],
)
def test_tires_season(client_car, today, status, season):
    with freeze_time(today):
        found = [r for r in journal.reminders(client_car, []) if r.kind == "tires"]
    if status is None:
        assert found == []
    else:
        assert (found[0].status, found[0].season) == (status, season)


@freeze_time("2026-10-15")
def test_tires_done_is_quiet(client_car):
    rows = [journal.Item(id="x", kind="tires", date=date(2026, 9, 25), mileage=None, amount=None,
                         liters=None, full_tank=True, note="", source="manual")]
    assert [r for r in journal.reminders(client_car, rows) if r.kind == "tires"] == []


def test_bad_oil_interval_is_rejected(auth, client_user, client_car):
    resp = auth(client_user).patch(
        reverse("v1:garage:car-detail", args=[client_car.pk]), {"oil_interval_km": 50},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "car_oil_interval_invalid"


# ----------------------------------------------------------- статистика
@freeze_time("2026-10-07")
def test_month_and_year_stats(auth, client_user, client_car):
    add(client_car, EntryKind.FUEL, date(2026, 10, 2), mileage=60500, amount=Decimal(2600),
        liters=Decimal(40))
    add(client_car, EntryKind.WASH, date(2026, 10, 3), amount=Decimal(900))
    add(client_car, EntryKind.FINE, date(2026, 5, 3), amount=Decimal(500), mileage=55000)
    add(client_car, EntryKind.FUEL, date(2026, 9, 28), mileage=60000, amount=Decimal(2400),
        liters=Decimal(38))

    body = auth(client_user).get(summary_url(client_car)).json()

    month = body["month"]
    assert Decimal(month["total"]) == Decimal(3500)
    assert [k["kind"] for k in month["by_kind"]] == ["fuel", "wash"]  # по убыванию
    assert month["distance"] == 500  # от последнего до 1 октября
    assert Decimal(body["year"]["total"]) == Decimal(6400)
    assert body["mileage"] == 60500
    assert body["oil_interval_km"] == 10000
