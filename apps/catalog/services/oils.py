"""Ассортимент масел и остатки — то, что правит мастер на сайте.

Каталог общий на всю сеть, а остатки — по точкам. Мастер видит и меняет
остатки только своих точек (`accessible_point_ids`), администратор — всех.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from apps.catalog.models import Oil, OilStock, ServicePoint
from apps.common.exceptions import ConflictError, NotFoundError, PermissionError_

#: Поля масла, которые можно задать с сайта. Остальное (описание) — в админке.
EDITABLE_FIELDS = (
    "brand", "name", "viscosity", "oil_type", "volume_liters", "price", "work_price", "is_active",
)


def _points_for(staff):
    qs = ServicePoint.objects.filter(is_active=True)
    allowed = staff.accessible_point_ids()
    if allowed is not None:
        qs = qs.filter(id__in=allowed)
    return qs.order_by("name")


def _check_point(staff, point_id) -> ServicePoint:
    try:
        point = ServicePoint.objects.get(pk=point_id)
    except (ServicePoint.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Точка не найдена", code="point_not_found") from exc
    allowed = staff.accessible_point_ids()
    if allowed is not None and point.pk not in allowed:
        raise PermissionError_("Это не ваша точка", code="point_not_allowed")
    return point


def catalog_for(staff) -> tuple[list[ServicePoint], list[Oil]]:
    """Точки сотрудника и все масла с остатками по этим точкам.

    Остатки подкладываются в `oil.stock_by_point` — одним запросом на все
    масла, а не по запросу на строку таблицы.
    """
    points = list(_points_for(staff))
    oils = list(Oil.objects.order_by("-is_active", "brand", "name"))
    stocks = OilStock.objects.filter(service_point__in=points, oil__in=oils)
    by_oil: dict = {}
    for stock in stocks:
        by_oil.setdefault(stock.oil_id, {})[stock.service_point_id] = stock.quantity
    for oil in oils:
        oil.stock_by_point = by_oil.get(oil.pk, {})
    return points, oils


@transaction.atomic
def create_oil(staff, *, stock: dict | None = None, **fields) -> Oil:
    """Новое масло в каталог и, сразу, его остатки на точках мастера."""
    data = {key: value for key, value in fields.items() if key in EDITABLE_FIELDS}
    try:
        with transaction.atomic():
            oil = Oil.objects.create(**data)
    except IntegrityError as exc:
        raise ConflictError(
            "Такое масло уже есть в каталоге: бренд, название, вязкость и объём совпадают",
            code="oil_exists",
        ) from exc

    for point_id, quantity in (stock or {}).items():
        set_stock(staff, oil.pk, point_id, quantity)
    return oil


@transaction.atomic
def update_oil(staff, oil_id, **fields) -> Oil:
    try:
        oil = Oil.objects.select_for_update().get(pk=oil_id)
    except (Oil.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Масло не найдено", code="oil_not_found") from exc

    changed = [key for key in fields if key in EDITABLE_FIELDS]
    for key in changed:
        setattr(oil, key, fields[key])
    if changed:
        try:
            with transaction.atomic():
                oil.save(update_fields=[*changed, "updated_at"])
        except IntegrityError as exc:
            raise ConflictError(
                "Такое масло уже есть в каталоге", code="oil_exists"
            ) from exc
    return oil


@transaction.atomic
def set_stock(staff, oil_id, point_id, quantity: int) -> OilStock:
    """Остаток после пересчёта или прихода — абсолютное число канистр.

    Абсолютное, а не «плюс N»: мастер пересчитывает полку и вводит то, что
    видит. Приращение при двойном нажатии задвоило бы приход.
    """
    point = _check_point(staff, point_id)
    if not Oil.objects.filter(pk=oil_id).exists():
        raise NotFoundError("Масло не найдено", code="oil_not_found")
    stock, _ = OilStock.objects.select_for_update().get_or_create(
        service_point=point, oil_id=oil_id
    )
    stock.quantity = quantity
    stock.save(update_fields=["quantity", "updated_at"])
    return stock
