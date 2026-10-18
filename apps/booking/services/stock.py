"""Доступность услуг на точке.

Остаток услуги (`Service.quantity`) записями не уменьшается — иначе
пришлось бы возвращать его при каждой отмене и ловить рассинхрон.
Вместо этого доступность считается как остаток минус то, что уже
обещано: позиции активных записей плюс живые черновики.

Остаток ведётся только у услуг с галочкой «ограничено»: канистры
кончаются, мойка — нет. У неограниченной услуги доступность не
считается вовсе, и `available_quantity` у неё пустое.

Списание происходит ровно один раз — при переводе записи в «Выполнена».
"""

from __future__ import annotations

from collections import Counter

from django.db.models import Count, F, Sum
from django.db.models.functions import Greatest

from apps.booking.constants import ACTIVE_BOOKING_STATUSES
from apps.booking.models import BookingDraft, BookingItem
from apps.catalog.models import OilStock, Service, ServiceCategory, ServicePoint
from apps.common.exceptions import ConflictError, NotFoundError


def reserved_by_service(point: ServicePoint, *, exclude_draft_id=None) -> Counter:
    """Сколько единиц каждой услуги уже обещано клиентам на этой точке."""
    reserved: Counter = Counter()

    booked = (
        BookingItem.objects.filter(
            booking__service_point=point,
            booking__status__in=ACTIVE_BOOKING_STATUSES,
        )
        .values("service_id")
        .annotate(n=Sum("quantity"))
    )
    for row in booked:
        reserved[row["service_id"]] += row["n"]

    held = (
        BookingDraft.objects.alive()
        .filter(service_point=point, service__isnull=False)
        .exclude(pk=exclude_draft_id)
        .values("service_id")
        .annotate(n=Count("id"))
    )
    for row in held:
        reserved[row["service_id"]] += row["n"]

    return reserved


def _is_available(service: Service, reserved: Counter) -> bool:
    """Можно ли обещать услугу ещё раз. Заодно проставляет
    `available_quantity`: число у ограниченной, пусто у остальных.

    Остаток считается и отрицательным — например, полку пересчитали в
    меньшую сторону, когда записи уже стояли. Это «нельзя», как и ноль.
    """
    if not service.is_limited:
        service.available_quantity = None
        return True
    service.available_quantity = service.quantity - reserved.get(service.pk, 0)
    return service.available_quantity > 0


def available_categories(point: ServicePoint) -> list[ServiceCategory]:
    """Категории точки, в которых клиенту есть что выбрать.

    Пустая категория клиенту не показывается: открыть её и упереться в
    «ничего нет» — то же самое, что показать неработающую кнопку.
    Категория с разрешённым «подберите на месте» остаётся даже пустой:
    в ней клиент как раз и просит подобрать.
    """
    reserved = reserved_by_service(point)
    categories = (
        ServiceCategory.objects.filter(service_point=point, is_active=True)
        .prefetch_related("services")
        .order_by("sort_order", "name")
    )

    result: list[ServiceCategory] = []
    for category in categories:
        services = [
            service
            for service in category.services.all()
            if service.is_active and _is_available(service, reserved)
        ]
        if services or category.allow_on_site:
            category.available_services = services
            result.append(category)
    return result


def available_services(
    point: ServicePoint, *, category=None, exclude_draft_id=None
) -> list[Service]:
    """Услуги, которые реально можно выбрать здесь и сейчас.

    Каждой проставляется `available_quantity` — сериализатор мастера
    отдаёт его, чтобы было видно «осталось 2». Клиенту остаток не
    показываем вместе с ценами.
    """
    reserved = reserved_by_service(point, exclude_draft_id=exclude_draft_id)

    # `oil` в выборке — ради старого API масел: оно отвечает из этих же
    # услуг, и без join ходило бы в базу за каждой канистрой.
    services = Service.objects.filter(
        category__service_point=point, category__is_active=True, is_active=True
    ).select_related("category", "oil")
    if category is not None:
        services = services.filter(category=category)

    result: list[Service] = []
    for service in services.order_by(
        "category__sort_order", "category__name", "sort_order", "name"
    ):
        if not _is_available(service, reserved):
            continue
        result.append(service)
    return result


def get_available_service(
    point: ServicePoint, service_id, *, exclude_draft_id=None
) -> Service:
    """Достать услугу и убедиться, что её ещё можно обещать."""
    try:
        service = Service.objects.select_related("category").get(
            pk=service_id,
            category__service_point=point,
            category__is_active=True,
            is_active=True,
        )
    except (Service.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError(
            "Такой услуги нет на выбранной точке", code="service_not_available"
        ) from exc

    reserved = reserved_by_service(point, exclude_draft_id=exclude_draft_id)
    if not _is_available(service, reserved):
        raise ConflictError(
            "Эту услугу только что разобрали, выберите другую",
            code="service_out_of_stock",
        )
    return service


def get_category(point: ServicePoint, category_id) -> ServiceCategory:
    try:
        return ServiceCategory.objects.get(
            pk=category_id, service_point=point, is_active=True
        )
    except (ServiceCategory.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError(
            "Такой категории нет на выбранной точке", code="category_not_available"
        ) from exc


def write_off(booking) -> None:
    """Списать остатки по позициям записи — по факту выполнения работ.

    Трогаем только ограниченные услуги: у остальных остаток не ведётся.
    `Greatest` страхует от ухода в минус — поле неотрицательное, и
    расхождение (списали вручную, пересчитали полку) не должно ронять
    расчёт, за которым стоит живой клиент.
    """
    for item in booking.items.select_related("service"):
        if not item.service.is_limited:
            continue
        Service.objects.filter(pk=item.service_id).update(
            quantity=Greatest(F("quantity") - item.quantity, 0)
        )
        # Пока старый раздел «Масла и склад» жив, он читает `OilStock`:
        # без этого он показывал бы прежний остаток, а первая же правка
        # оттуда перезаписала бы настоящий (см. `oils.mirror_oil`). Мост
        # работает в обе стороны и уйдёт вместе со старым разделом.
        if item.service.oil_id:
            OilStock.objects.filter(
                service_point_id=booking.service_point_id, oil_id=item.service.oil_id
            ).update(quantity=Greatest(F("quantity") - item.quantity, 0))
