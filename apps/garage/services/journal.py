"""Дневник водителя: записи по машине, расход, напоминания, статистика.

Замены масла, сделанные у нас, в дневник не копируются: они берутся из
выполненных записей на эту машину при каждом чтении. Копия разошлась бы
с записью, когда мастер поправит итог, — а так дневник всегда показывает
то, что клиент заплатил.

Всё считается при чтении, а не хранится: записей у одной машины — сотни,
а не миллионы, и пересчёт при каждом открытии дешевле, чем следить за
согласованностью сохранённых итогов.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.booking.constants import BookingStatus
from apps.booking.models import Booking
from apps.common.exceptions import NotFoundError, ValidationError
from apps.garage.models import Car, EntryKind, LogEntry
from apps.garage.services.cars import MAX_MILEAGE_KM, get_car

MAX_AMOUNT = Decimal("10000000")
MAX_LITERS = Decimal("500")
EARLIEST = date(1990, 1, 1)
# Пробег «на дату» без записи в этот день: берём ближайшую запись с
# пробегом, если она не дальше этого числа дней. Нужно для замен у нас —
# в записи на сервис пробега нет.
MILEAGE_NEAR_DAYS = 14

ENTRY_FIELDS = ("kind", "date", "mileage", "amount", "liters", "full_tank", "note")


@dataclass(frozen=True)
class Item:
    """Строка дневника: своя запись клиента или замена масла у нас."""

    id: str
    kind: str
    date: date
    mileage: int | None
    amount: Decimal | None
    liters: Decimal | None
    full_tank: bool
    note: str
    source: str  # manual — клиент добавил сам, booking — замена у нас
    booking_code: str = ""

    @property
    def kind_display(self) -> str:
        return EntryKind(self.kind).label

    @property
    def editable(self) -> bool:
        return self.source == "manual"


def today() -> date:
    return timezone.localdate()


# ------------------------------------------------------------- записи
def _clean(fields: dict, *, kind: str | None) -> dict:
    data = {key: value for key, value in fields.items() if key in ENTRY_FIELDS}
    kind = data.get("kind", kind)
    if kind not in EntryKind.values:
        raise ValidationError("Неизвестный тип записи", code="entry_kind_invalid")

    latest = today() + timedelta(days=1)
    if "date" in data and (data["date"] is None or not EARLIEST <= data["date"] <= latest):
        raise ValidationError("Проверьте дату", code="entry_date_invalid")
    if data.get("mileage") is not None and not 0 <= int(data["mileage"]) <= MAX_MILEAGE_KM:
        raise ValidationError("Проверьте пробег", code="car_mileage_invalid")
    if data.get("amount") is not None and not Decimal(0) <= data["amount"] <= MAX_AMOUNT:
        raise ValidationError("Проверьте сумму", code="entry_amount_invalid")
    if data.get("liters") is not None and not Decimal(0) < data["liters"] <= MAX_LITERS:
        raise ValidationError("Проверьте литры", code="entry_liters_invalid")
    if "note" in data:
        data["note"] = " ".join((data["note"] or "").split())[:200]

    if kind != EntryKind.FUEL:
        # Литры и «полный бак» бывают только у заправки.
        data["liters"] = None
        data["full_tank"] = True
    return data


def _touch_mileage(car: Car, mileage: int | None) -> None:
    """Пробег машины — наибольший известный: из карточки и из дневника."""
    if mileage is not None and (car.mileage is None or mileage > car.mileage):
        car.mileage = mileage
        car.save(update_fields=["mileage", "updated_at"])


@transaction.atomic
def add_entry(user, car_id, **fields) -> LogEntry:
    car = get_car(user, car_id)
    data = _clean(fields, kind=fields.get("kind"))
    data.setdefault("date", today())
    if data["kind"] == EntryKind.FUEL and data.get("liters") is None:
        raise ValidationError("Сколько литров залили?", code="entry_liters_required")
    entry = LogEntry.objects.create(car=car, **data)
    _touch_mileage(car, entry.mileage)
    return entry


def _own_entry(user, entry_id) -> LogEntry:
    try:
        return LogEntry.objects.select_related("car").get(
            pk=entry_id, car__user=user, car__archived_at__isnull=True
        )
    except (LogEntry.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Запись не найдена", code="entry_not_found") from exc


@transaction.atomic
def update_entry(user, entry_id, **fields) -> LogEntry:
    entry = _own_entry(user, entry_id)
    data = _clean(fields, kind=entry.kind)
    for key, value in data.items():
        setattr(entry, key, value)
    if entry.kind == EntryKind.FUEL and entry.liters is None:
        raise ValidationError("Сколько литров залили?", code="entry_liters_required")
    entry.save()
    _touch_mileage(entry.car, entry.mileage)
    return entry


@transaction.atomic
def delete_entry(user, entry_id) -> None:
    _own_entry(user, entry_id).delete()


# ------------------------------------------------------------- дневник
def _our_oil_changes(car: Car) -> list[Item]:
    bookings = Booking.objects.filter(car=car, status=BookingStatus.COMPLETED).select_related(
        "service_point"
    )
    return [
        Item(
            id=f"booking-{b.pk}",
            kind=EntryKind.OIL,
            date=b.local_start().date(),
            mileage=None,
            # Деньгами: баллы — скидка, а не расход владельца.
            amount=b.paid_amount,
            liters=None,
            full_tank=True,
            note=f"{b.oil_title} · {b.service_point.name}",
            source="booking",
            booking_code=b.code,
        )
        for b in bookings
    ]


def _manual(car: Car) -> list[Item]:
    return [
        Item(
            id=str(e.pk), kind=e.kind, date=e.date, mileage=e.mileage, amount=e.amount,
            liters=e.liters, full_tank=e.full_tank, note=e.note, source="manual",
        )
        for e in car.entries.all()
    ]


def items(car: Car) -> list[Item]:
    """Весь дневник машины, новые сверху."""
    rows = _manual(car) + _our_oil_changes(car)
    return sorted(rows, key=lambda r: (r.date, r.mileage or 0), reverse=True)


def journal(user, car_id, *, limit: int = 50) -> list[Item]:
    return items(get_car(user, car_id))[: max(1, min(limit, 500))]


# ------------------------------------------------------------- расход
@dataclass(frozen=True)
class Fuel:
    average: Decimal | None  # л/100 км за всё время, по полным бакам
    last: Decimal | None  # последний отрезок от полного до полного
    distance: int  # км, на которых посчитан средний


def fuel(rows: list[Item]) -> Fuel:
    """Расход от полного бака до полного.

    Отрезок закрывает только полная заправка: литры неполных до неё
    прибавляются к отрезку, а пробег берётся между двумя полными. Заправки
    без пробега расчёт не ломают — их литры просто уходят в отрезок.
    """
    fills = sorted(
        (r for r in rows if r.kind == EntryKind.FUEL and r.liters),
        key=lambda r: (r.date, r.mileage or 0),
    )
    segments: list[tuple[Decimal, int]] = []
    start_km: int | None = None
    liters = Decimal(0)
    for fill in fills:
        if start_km is None:
            if fill.full_tank and fill.mileage is not None:
                start_km = fill.mileage
            continue
        liters += fill.liters
        if fill.full_tank and fill.mileage is not None:
            distance = fill.mileage - start_km
            if distance > 0:
                segments.append((liters, distance))
            start_km = fill.mileage
            liters = Decimal(0)

    if not segments:
        return Fuel(average=None, last=None, distance=0)
    total_l = sum(seg[0] for seg in segments)
    total_km = sum(seg[1] for seg in segments)
    last_liters, last_km = segments[-1]
    return Fuel(
        average=_per_100(total_l, total_km),
        last=_per_100(last_liters, last_km),
        distance=total_km,
    )


def _per_100(liters: Decimal, km: int) -> Decimal:
    return (liters * 100 / km).quantize(Decimal("0.1"))


# ------------------------------------------------------------- пробег
def mileage_now(car: Car, rows: list[Item]) -> int | None:
    known = [r.mileage for r in rows if r.mileage is not None]
    if car.mileage is not None:
        known.append(car.mileage)
    return max(known) if known else None


def mileage_near(rows: list[Item], day: date) -> int | None:
    """Пробег около даты — по ближайшей записи с пробегом, если она близко."""
    best = None
    for r in rows:
        if r.mileage is None:
            continue
        gap = abs((r.date - day).days)
        if gap <= MILEAGE_NEAR_DAYS and (best is None or gap < best[0]):
            best = (gap, r.mileage)
    return best[1] if best else None


# ------------------------------------------------------------- напоминания
def add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class Reminder:
    kind: str  # oil | osago | inspection | tires
    status: str  # overdue | soon | ok | unknown
    due_date: date | None = None
    left_days: int | None = None
    due_km: int | None = None
    left_km: int | None = None
    season: str = ""  # tires: summer | winter
    last_date: date | None = None


def _status(left_days: int | None, left_km: int | None) -> str:
    conf = settings.GARAGE
    if (left_days is not None and left_days < 0) or (left_km is not None and left_km < 0):
        return "overdue"
    if (left_days is not None and left_days <= conf["SOON_DAYS"]) or (
        left_km is not None and left_km <= conf["SOON_KM"]
    ):
        return "soon"
    return "ok"


def _oil(car: Car, rows: list[Item], now_km: int | None, on: date) -> Reminder:
    changes = [r for r in rows if r.kind == EntryKind.OIL]
    if not changes:
        return Reminder(kind="oil", status="unknown")
    last = max(changes, key=lambda r: (r.date, r.mileage or 0))
    interval_km = car.oil_interval_km or settings.GARAGE["OIL_INTERVAL_KM"]
    interval_months = car.oil_interval_months or settings.GARAGE["OIL_INTERVAL_MONTHS"]

    due_date = add_months(last.date, interval_months)
    left_days = (due_date - on).days
    last_km = last.mileage if last.mileage is not None else mileage_near(rows, last.date)
    due_km = last_km + interval_km if last_km is not None else None
    left_km = due_km - now_km if due_km is not None and now_km is not None else None
    return Reminder(
        kind="oil", status=_status(left_days, left_km), due_date=due_date,
        left_days=left_days, due_km=due_km, left_km=left_km, last_date=last.date,
    )


def _document(kind: str, until: date | None, on: date) -> Reminder | None:
    if until is None:
        return None
    left = (until - on).days
    return Reminder(kind=kind, status=_status(left, None), due_date=until, left_days=left)


def _parse_md(value: str, year: int) -> date:
    month, day = (int(part) for part in value.split("-"))
    return date(year, month, day)


def _tires(rows: list[Item], on: date) -> Reminder | None:
    """Смена резины по сезону: за `SOON_DAYS` до даты и месяц после неё.

    Уже поменяли (запись «Шиномонтаж» в этом окне) — не напоминаем.
    """
    conf = settings.GARAGE
    window_before = timedelta(days=conf["SOON_DAYS"])
    window_after = timedelta(days=30)
    for year in (on.year - 1, on.year, on.year + 1):
        for season, key in (("summer", "SUMMER_TIRES_FROM"), ("winter", "WINTER_TIRES_FROM")):
            switch = _parse_md(conf[key], year)
            if not switch - window_before <= on < switch + window_after:
                continue
            done = any(
                r.kind == EntryKind.TIRES and r.date >= switch - window_before for r in rows
            )
            if done:
                return None
            left = (switch - on).days
            return Reminder(
                kind="tires", status="soon" if left > 0 else "overdue",
                due_date=switch, left_days=left, season=season,
            )
    return None


def reminders(car: Car, rows: list[Item], *, on: date | None = None) -> list[Reminder]:
    on = on or today()
    now_km = mileage_now(car, rows)
    found = [
        _oil(car, rows, now_km, on),
        _document("osago", car.osago_until, on),
        _document("inspection", car.inspection_until, on),
        _tires(rows, on),
    ]
    order = {"overdue": 0, "soon": 1, "unknown": 2, "ok": 3}
    return sorted((r for r in found if r), key=lambda r: order[r.status])


# ------------------------------------------------------------- статистика
@dataclass(frozen=True)
class Period:
    start: date
    end: date
    total: Decimal
    by_kind: dict
    distance: int | None


def period_stats(rows: list[Item], start: date, end: date) -> Period:
    by_kind: dict[str, Decimal] = defaultdict(Decimal)
    for r in rows:
        if start <= r.date <= end and r.amount:
            by_kind[r.kind] += r.amount
    # Пробег за период: от последнего известного до начала периода (или от
    # первого внутри него) до наибольшего внутри.
    inside = [r.mileage for r in rows if r.mileage is not None and start <= r.date <= end]
    before = [r.mileage for r in rows if r.mileage is not None and r.date < start]
    distance = None
    if inside:
        base = max(before) if before else min(inside)
        distance = max(0, max(inside) - base)
    ordered = dict(sorted(by_kind.items(), key=lambda kv: kv[1], reverse=True))
    return Period(start=start, end=end, total=sum(by_kind.values(), Decimal(0)),
                  by_kind=ordered, distance=distance)


def summary(user, car_id) -> dict:
    """Всё для главного экрана гаража одним ответом."""
    car = get_car(user, car_id)
    rows = items(car)
    on = today()
    return {
        "car": car,
        "mileage": mileage_now(car, rows),
        "oil_interval_km": car.oil_interval_km or settings.GARAGE["OIL_INTERVAL_KM"],
        "oil_interval_months": car.oil_interval_months or settings.GARAGE["OIL_INTERVAL_MONTHS"],
        "reminders": reminders(car, rows, on=on),
        "month": period_stats(rows, on.replace(day=1), on),
        "year": period_stats(rows, on.replace(month=1, day=1), on),
        "fuel": fuel(rows),
        "recent": rows[:5],
    }
