"""Сводная аналитика для администратора.

Отдельный модуль, а не код во вьюхе: считается тут заметно больше, чем в
`summary` за день, и это чистое чтение — вьюха остаётся тонкой, как того
требует правило слоёв.

Все выборки идут по локальным суткам сети (`BUSINESS_TIMEZONE`) либо по
поясу конкретной точки, если её выбрали фильтром: в базе всё в UTC, а
администратор думает про «вчера» и «эта неделя» в своём часовом поясе.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Avg, Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, ExtractHour, TruncDate
from django.utils import timezone

from apps.accounts.constants import UserRole
from apps.accounts.models import User
from apps.booking.constants import ACTIVE_BOOKING_STATUSES, BookingStatus
from apps.booking.models import Booking, BookingDraft
from apps.catalog.models import OilStock, ServicePoint

#: Ниже какого остатка канистр позиция попадает в «заканчивается».
LOW_STOCK_THRESHOLD = 5

_CANCELLED = [
    BookingStatus.CANCELLED_BY_CLIENT,
    BookingStatus.CANCELLED_BY_MASTER,
]

_MONEY = DecimalField(max_digits=12, decimal_places=2)


#: Выручка — то, что пришло деньгами: чек минус часть, закрытая баллами.
#: Баллы — скидка, в кассу они не приходят, и считать их выручкой значило
#: бы завышать её ровно на размер программы лояльности.
PAID = F("total_price") - F("points_spent")


def _zero() -> Value:
    """Ноль нужного типа: Coalesce требует совпадения типов с Sum(Decimal)."""
    return Value(Decimal("0"), output_field=_MONEY)


@dataclass(frozen=True)
class Period:
    """Отрезок анализа: локальные даты плюс их границы в UTC."""

    date_from: date
    date_to: date
    tz: zoneinfo.ZoneInfo

    @property
    def since(self) -> datetime:
        return datetime.combine(self.date_from, time.min, tzinfo=self.tz)

    @property
    def until(self) -> datetime:
        # Правая граница — начало следующих суток: полуинтервал [since, until)
        # не теряет записи, попавшие в последнюю секунду дня.
        return datetime.combine(self.date_to, time.min, tzinfo=self.tz) + timedelta(days=1)

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1


def resolve_period(
    raw_from: str | None,
    raw_to: str | None,
    point: ServicePoint | None,
    *,
    default_days: int = 30,
) -> Period:
    """Период из query-параметров. По умолчанию — последние 30 дней включительно."""
    tz = point.tz if point is not None else zoneinfo.ZoneInfo(settings.BUSINESS_TIMEZONE)
    today = timezone.now().astimezone(tz).date()

    date_to = _parse_date(raw_to) if raw_to else today
    date_from = _parse_date(raw_from) if raw_from else date_to - timedelta(days=default_days - 1)

    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return Period(date_from=date_from, date_to=date_to, tz=tz)


def _parse_date(raw: str) -> date:
    from apps.common.exceptions import ValidationError

    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(
            "Дата должна быть в формате YYYY-MM-DD", code="bad_date"
        ) from exc


def collect(period: Period, point: ServicePoint | None) -> dict:
    """Все метрики одним вызовом.

    Возвращает готовый к отдаче словарь: во вьюхе не остаётся ни одного
    вычисления, а фронтенд не склеивает несколько запросов ради одного экрана.
    """
    bookings = Booking.objects.filter(start_at__gte=period.since, start_at__lt=period.until)
    drafts = BookingDraft.objects.filter(
        created_at__gte=period.since, created_at__lt=period.until
    )
    if point is not None:
        bookings = bookings.filter(service_point=point)
        drafts = drafts.filter(service_point=point)

    return {
        "period": {
            "date_from": period.date_from,
            "date_to": period.date_to,
            "days": period.days,
            "timezone": str(period.tz),
        },
        "totals": _totals(bookings),
        "funnel": _funnel(drafts),
        "by_day": _by_day(bookings, period),
        "by_hour": _by_hour(bookings, period),
        "by_point": _by_point(bookings, point),
        "top_oils": _top_oils(bookings),
        "clients": _clients(period),
        "stock": _stock(point),
        "live": _live(point),
    }


def _totals(bookings) -> dict:
    """Ключевые цифры за период плюс производные доли."""
    stats = bookings.aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(status=BookingStatus.COMPLETED)),
        pending=Count("id", filter=Q(status=BookingStatus.PENDING)),
        in_progress=Count("id", filter=Q(status=BookingStatus.IN_PROGRESS)),
        cancelled_by_client=Count("id", filter=Q(status=BookingStatus.CANCELLED_BY_CLIENT)),
        cancelled_by_master=Count("id", filter=Q(status=BookingStatus.CANCELLED_BY_MASTER)),
        no_show=Count("id", filter=Q(status=BookingStatus.NO_SHOW)),
        revenue=Coalesce(
            Sum(PAID, filter=Q(status=BookingStatus.COMPLETED)), _zero()
        ),
        avg_check=Coalesce(
            Avg("total_price", filter=Q(status=BookingStatus.COMPLETED)), _zero()
        ),
        oil_revenue=Coalesce(
            Sum("oil_price", filter=Q(status=BookingStatus.COMPLETED)), _zero()
        ),
        work_revenue=Coalesce(
            Sum("work_price", filter=Q(status=BookingStatus.COMPLETED)), _zero()
        ),
        points_spent=Coalesce(
            Sum("points_spent", filter=Q(status=BookingStatus.COMPLETED)), _zero()
        ),
    )

    total = stats["total"]
    cancelled = stats["cancelled_by_client"] + stats["cancelled_by_master"]
    stats["cancelled"] = cancelled
    # Доли считаем здесь, а не на фронте: одна формула — один результат
    # во всех клиентах, которые когда-нибудь подключатся к этому API.
    stats["cancel_rate"] = _percent(cancelled, total)
    stats["no_show_rate"] = _percent(stats["no_show"], total)
    stats["completion_rate"] = _percent(stats["completed"], total)
    return stats


def _funnel(drafts) -> dict:
    """Воронка записи: где именно клиенты отваливаются.

    Шаг черновика после закрытия перезаписывается на `expired`/`cancelled`,
    поэтому глубину считаем по заполненным полям — они сохраняются как есть
    и честно показывают, до какого шага человек дошёл.
    """
    stats = drafts.aggregate(
        started=Count("id"),
        point_selected=Count("id", filter=Q(service_point__isnull=False)),
        oil_selected=Count("id", filter=Q(oil__isnull=False)),
        slot_selected=Count("id", filter=Q(slot_start__isnull=False)),
        confirmed=Count("id", filter=Q(booking__isnull=False)),
        expired=Count("id", filter=Q(close_reason="expired")),
        cancelled=Count("id", filter=Q(close_reason="cancelled")),
        restarted=Count("id", filter=Q(close_reason="restarted")),
        alive=Count("id", filter=Q(is_open=True)),
    )
    started = stats["started"]
    stats["conversion"] = _percent(stats["confirmed"], started)
    stats["steps"] = [
        {"key": key, "label": label, "count": count, "share": _percent(count, started)}
        for key, label, count in (
            ("started", "Начали запись", started),
            ("point", "Выбрали адрес", stats["point_selected"]),
            ("oil", "Выбрали масло", stats["oil_selected"]),
            ("slot", "Выбрали время", stats["slot_selected"]),
            ("confirmed", "Подтвердили", stats["confirmed"]),
        )
    ]
    return stats


def _by_day(bookings, period: Period) -> list[dict]:
    """Динамика по дням. Пустые дни заполняются нулями — иначе график врёт."""
    rows = (
        bookings.annotate(day=TruncDate("start_at", tzinfo=period.tz))
        .values("day")
        .annotate(
            total=Count("id"),
            completed=Count("id", filter=Q(status=BookingStatus.COMPLETED)),
            cancelled=Count("id", filter=Q(status__in=_CANCELLED)),
            revenue=Coalesce(
                Sum(PAID, filter=Q(status=BookingStatus.COMPLETED)), _zero()
            ),
        )
    )
    known = {row["day"]: row for row in rows}

    out = []
    day = period.date_from
    while day <= period.date_to:
        row = known.get(day)
        out.append(
            {
                "date": day,
                "total": row["total"] if row else 0,
                "completed": row["completed"] if row else 0,
                "cancelled": row["cancelled"] if row else 0,
                "revenue": row["revenue"] if row else Decimal("0"),
            }
        )
        day += timedelta(days=1)
    return out


def _by_hour(bookings, period: Period) -> list[dict]:
    """Загрузка по часам — видно, когда сервис стоит, а когда очередь."""
    rows = (
        bookings.annotate(hour=ExtractHour("start_at", tzinfo=period.tz))
        .values("hour")
        .annotate(total=Count("id"))
    )
    known = {row["hour"]: row["total"] for row in rows}
    return [{"hour": hour, "total": known.get(hour, 0)} for hour in range(24)]


def _by_point(bookings, point: ServicePoint | None) -> list[dict]:
    """Сравнение точек между собой. При фильтре по точке — она одна."""
    rows = (
        bookings.values("service_point_id", name=F("service_point__name"))
        .annotate(
            total=Count("id"),
            completed=Count("id", filter=Q(status=BookingStatus.COMPLETED)),
            cancelled=Count("id", filter=Q(status__in=_CANCELLED)),
            revenue=Coalesce(
                Sum(PAID, filter=Q(status=BookingStatus.COMPLETED)), _zero()
            ),
        )
        .order_by("-revenue")
    )
    return [
        {
            "id": str(row["service_point_id"]),
            "name": row["name"],
            "total": row["total"],
            "completed": row["completed"],
            "cancelled": row["cancelled"],
            "revenue": row["revenue"],
        }
        for row in rows
    ]


def _top_oils(bookings, limit: int = 8) -> list[dict]:
    """Что реально продаётся. Берём снимок названия из записи, а не справочник:
    масло могли переименовать или снять с продажи, история это переживёт."""
    rows = (
        bookings.values("oil_title")
        .annotate(
            total=Count("id"),
            completed=Count("id", filter=Q(status=BookingStatus.COMPLETED)),
            revenue=Coalesce(
                Sum(PAID, filter=Q(status=BookingStatus.COMPLETED)), _zero()
            ),
        )
        .order_by("-total")[:limit]
    )
    return list(rows)


def _clients(period: Period) -> dict:
    """Клиентская база: сколько всего и сколько пришло за период."""
    clients = User.objects.filter(role=UserRole.CLIENT)
    new = clients.filter(
        date_joined__gte=period.since, date_joined__lt=period.until
    ).count()

    # Повторные — те, у кого больше одной непустой записи за всё время.
    returning = (
        Booking.objects.values("user_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .count()
    )
    return {"total": clients.count(), "new": new, "returning": returning}


def _stock(point: ServicePoint | None) -> dict:
    """Склад на сейчас — это срез, а не история, поэтому период не применяем."""
    qs = OilStock.objects.select_related("service_point", "oil")
    if point is not None:
        qs = qs.filter(service_point=point)

    items = [
        {
            "point": row.service_point.name,
            "oil": str(row.oil),
            "quantity": row.quantity,
            "is_low": row.quantity <= LOW_STOCK_THRESHOLD,
        }
        for row in qs.order_by("quantity", "service_point__name")
    ]
    return {
        "threshold": LOW_STOCK_THRESHOLD,
        "total_quantity": sum(item["quantity"] for item in items),
        "low_count": sum(1 for item in items if item["is_low"]),
        "items": items,
    }


def _live(point: ServicePoint | None) -> dict:
    """Что происходит прямо сейчас: живые черновики и ближайшие записи."""
    drafts = BookingDraft.objects.alive()
    active = Booking.objects.filter(
        status__in=ACTIVE_BOOKING_STATUSES, start_at__gte=timezone.now()
    )
    if point is not None:
        drafts = drafts.filter(service_point=point)
        active = active.filter(service_point=point)
    return {"drafts_now": drafts.count(), "upcoming": active.count()}


def _percent(part: int, whole: int) -> float:
    """Доля в процентах с одним знаком. Ноль на ноль — ноль, а не ошибка."""
    if not whole:
        return 0.0
    return round(part * 100 / whole, 1)
