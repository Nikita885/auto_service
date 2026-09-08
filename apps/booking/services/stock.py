"""Доступность масла на точке.

Физический остаток (`OilStock.quantity`) записями не уменьшается — иначе
пришлось бы возвращать канистру при каждой отмене и ловить рассинхрон.
Вместо этого доступность считается как остаток минус то, что уже обещано:
активные записи плюс живые черновики.

Списание остатка происходит ровно один раз — при переводе записи в
«Выполнена».
"""

from __future__ import annotations

from collections import Counter

from django.db.models import Count, F

from apps.booking.constants import ACTIVE_BOOKING_STATUSES
from apps.booking.models import Booking, BookingDraft
from apps.catalog.models import Oil, OilStock, ServicePoint
from apps.common.exceptions import ConflictError, NotFoundError


def reserved_by_oil(point: ServicePoint, *, exclude_draft_id=None) -> Counter:
    """Сколько канистр каждого масла уже обещано клиентам на этой точке."""
    reserved: Counter = Counter()

    booked = (
        Booking.objects.filter(
            service_point=point, status__in=ACTIVE_BOOKING_STATUSES
        )
        .values("oil_id")
        .annotate(n=Count("id"))
    )
    for row in booked:
        reserved[row["oil_id"]] += row["n"]

    held = (
        BookingDraft.objects.alive()
        .filter(service_point=point, oil__isnull=False)
        .exclude(pk=exclude_draft_id)
        .values("oil_id")
        .annotate(n=Count("id"))
    )
    for row in held:
        reserved[row["oil_id"]] += row["n"]

    return reserved


def available_oils(point: ServicePoint, *, exclude_draft_id=None) -> list[Oil]:
    """Масла, которые реально можно выбрать здесь и сейчас.

    Каждому объекту проставляется `available_quantity` — сериализатор
    отдаёт его клиенту, чтобы в приложении было видно «осталось 2».
    """
    reserved = reserved_by_oil(point, exclude_draft_id=exclude_draft_id)

    stocks = (
        OilStock.objects.filter(
            service_point=point, oil__is_active=True, quantity__gt=0
        )
        .select_related("oil")
        .order_by("oil__brand", "oil__name")
    )

    result: list[Oil] = []
    for stock in stocks:
        available = stock.quantity - reserved.get(stock.oil_id, 0)
        if available <= 0:
            continue
        oil = stock.oil
        oil.available_quantity = available
        result.append(oil)
    return result


def get_available_oil(point: ServicePoint, oil_id, *, exclude_draft_id=None) -> Oil:
    """Достать масло и убедиться, что оно ещё есть. Иначе — доменная ошибка."""
    try:
        stock = OilStock.objects.select_related("oil").get(
            service_point=point, oil_id=oil_id, oil__is_active=True
        )
    except OilStock.DoesNotExist as exc:
        raise NotFoundError(
            "Такого масла нет на выбранной точке", code="oil_not_available"
        ) from exc

    reserved = reserved_by_oil(point, exclude_draft_id=exclude_draft_id)
    available = stock.quantity - reserved.get(stock.oil_id, 0)
    if available <= 0:
        raise ConflictError(
            "Это масло только что разобрали, выберите другое",
            code="oil_out_of_stock",
        )

    oil = stock.oil
    oil.available_quantity = available
    return oil


def write_off(booking) -> None:
    """Списать канистру со склада по факту выполнения работ."""
    OilStock.objects.filter(
        service_point_id=booking.service_point_id,
        oil_id=booking.oil_id,
        quantity__gt=0,
    ).update(quantity=F("quantity") - 1)
