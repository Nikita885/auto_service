"""Ассортимент масел и остатки — то, что правит мастер на сайте.

Каталог общий на всю сеть, а остатки — по точкам. Мастер видит и меняет
остатки только своих точек (`accessible_point_ids`), администратор — всех.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import (
    Oil,
    OilStock,
    Service,
    ServiceCategory,
    ServiceJournalKind,
    ServicePoint,
)
from apps.common.exceptions import ConflictError, NotFoundError, PermissionError_

#: Поля масла, которые можно задать с сайта. Остальное (описание) — в админке.
EDITABLE_FIELDS = (
    "brand", "name", "viscosity", "oil_type", "volume_liters", "price", "work_price", "is_active",
)

#: Категория, в которую легли масла при переносе (`catalog.0005`).
OIL_CATEGORY_NAME = "Замена масла"
#: Порядок показа: «Замена масла» — первая категория у всех точек.
OIL_CATEGORY_ORDER = 10


def _oil_category(point: ServicePoint) -> ServiceCategory:
    """Категория масел точки. Нет — создаём: масло не должно упираться в
    то, что категорию кто-то удалил из админки."""
    category, _ = ServiceCategory.objects.get_or_create(
        service_point=point,
        name=OIL_CATEGORY_NAME,
        defaults={
            "sort_order": OIL_CATEGORY_ORDER,
            "allow_on_site": True,
            "journal_kind": ServiceJournalKind.OIL,
        },
    )
    return category


def mirror_oil(oil: Oil, *, quantity_by_point: dict | None = None) -> None:
    """Отразить масло в услугах категории «Замена масла» на каждой точке.

    Пока панель мастера правит масла, а запись и доступность читают уже
    услуги, у одних и тех же цифр два места хранения. Если не писать в
    оба, мастер поменяет цену или пересчитает полку в старом разделе, а
    клиент увидит прежнее — то есть выкатка переноса в одиночку сломала
    бы работу. Этот мост уйдёт вместе со старым разделом масел.

    Услуга создаётся на всех точках, а не только на точках мастера:
    раньше новое масло появлялось в общем каталоге сети, и ни один адрес
    не должен потерять позицию прайса из-за того, что её завёл сосед.
    """
    title = str(oil)
    price = oil.price + oil.work_price
    quantities = quantity_by_point or {}
    for point in ServicePoint.objects.all():
        service = Service.objects.filter(category__service_point=point, oil=oil).first()
        fields = {
            "name": title,
            "price": price,
            # Канистра — материал внутри цены; работа считается как остаток.
            "material_price": oil.price,
            "is_limited": True,
            "is_active": oil.is_active,
            "description": oil.description,
        }
        if service is None:
            category = _oil_category(point)
            Service.objects.create(
                category=category, oil=oil, quantity=quantities.get(point.pk, 0), **fields
            )
            continue
        if point.pk in quantities:
            fields["quantity"] = quantities[point.pk]
        for key, value in fields.items():
            setattr(service, key, value)
        service.save(update_fields=[*fields, "updated_at"])


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


def available_oils_from_services(point: ServicePoint, *, exclude_draft_id=None) -> list[Oil]:
    """Масла в наличии для старого API — поверх услуг.

    Отвечаем из того же расчёта доступности, что и новые ручки: иначе
    приложение прежней версии показывало бы наличие, которого нет.
    Импорт локальный: `booking` зависит от `catalog`, и встречный импорт
    на уровне модуля замкнул бы приложения друг на друга.
    """
    from apps.booking.services import stock as stock_service

    oils: list[Oil] = []
    for service in stock_service.available_services(
        point, exclude_draft_id=exclude_draft_id
    ):
        if service.oil_id is None:
            continue
        oil = service.oil
        # У неограниченной услуги остатка нет вовсе; старое приложение
        # понимает только число, и единица для него значит «есть».
        oil.available_quantity = (
            service.available_quantity if service.available_quantity is not None else 1
        )
        oils.append(oil)
    return oils


def service_for_oil(point: ServicePoint, oil_id) -> Service:
    """Услуга, в которую перенесли это масло на этой точке.

    Опора старого API: приложение, которое ещё не обновилось, присылает
    id масла, а запись и расчёт живут уже на услугах.
    """
    try:
        service = Service.objects.select_related("category").filter(
            category__service_point=point, oil_id=oil_id
        ).first()
    except (ValueError, TypeError, DjangoValidationError) as exc:
        raise NotFoundError(
            "Такого масла нет на выбранной точке", code="oil_not_available"
        ) from exc
    if service is None:
        raise NotFoundError(
            "Такого масла нет на выбранной точке", code="oil_not_available"
        )
    return service


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
