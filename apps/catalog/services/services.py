"""Каталог услуг, который мастер ведёт сам.

Каталог у каждой точки свой (решение заказчика), поэтому всё здесь
начинается с проверки: эта ли точка принадлежит сотруднику. Мастер видит
и правит только свои точки, администратор — все (`accessible_point_ids`).

Категории и услуги не удаляются, а выключаются. Выключенная услуга
сразу пропадает у клиента, но уже созданные записи не меняются: в них
снимок названия и цены.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from apps.catalog.models import Service, ServiceCategory, ServicePoint
from apps.common.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionError_,
    ValidationError,
)

#: Поля категории, которые правятся с сайта.
CATEGORY_FIELDS = ("name", "sort_order", "is_active", "allow_on_site", "journal_kind")

#: Поля услуги, которые правятся с сайта.
SERVICE_FIELDS = (
    "name", "description", "price", "material_price",
    "is_limited", "quantity", "is_active", "sort_order",
)


def points_for(staff) -> list[ServicePoint]:
    qs = ServicePoint.objects.filter(is_active=True)
    allowed = staff.accessible_point_ids()
    if allowed is not None:
        qs = qs.filter(id__in=allowed)
    return list(qs.order_by("name"))


def _check_point(staff, point_id) -> ServicePoint:
    try:
        point = ServicePoint.objects.get(pk=point_id)
    except (ServicePoint.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Точка не найдена", code="point_not_found") from exc
    allowed = staff.accessible_point_ids()
    if allowed is not None and point.pk not in allowed:
        raise PermissionError_("Это не ваша точка", code="point_not_allowed")
    return point


def get_category(staff, category_id, *, lock: bool = False) -> ServiceCategory:
    qs = ServiceCategory.objects.select_related("service_point")
    if lock:
        qs = qs.select_for_update(of=("self",))
    try:
        category = qs.get(pk=category_id)
    except (ServiceCategory.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Категория не найдена", code="category_not_found") from exc
    _check_point(staff, category.service_point_id)
    return category


def get_service(staff, service_id, *, lock: bool = False) -> Service:
    qs = Service.objects.select_related("category__service_point")
    if lock:
        qs = qs.select_for_update(of=("self",))
    try:
        service = qs.get(pk=service_id)
    except (Service.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Услуга не найдена", code="service_not_found") from exc
    _check_point(staff, service.category.service_point_id)
    return service


def catalog_for(staff) -> list[ServiceCategory]:
    """Категории точек сотрудника вместе с услугами — одним запросом.

    Панель рисует дерево «категория → услуги», и ходить в базу за каждой
    строкой таблицы она не должна.
    """
    points = points_for(staff)
    return list(
        ServiceCategory.objects.filter(service_point__in=points)
        .select_related("service_point")
        .prefetch_related("services")
        .order_by("service_point__name", "sort_order", "name")
    )


@transaction.atomic
def create_category(staff, *, service_point, **fields) -> ServiceCategory:
    point = _check_point(staff, service_point)
    data = {key: value for key, value in fields.items() if key in CATEGORY_FIELDS}
    try:
        with transaction.atomic():
            return ServiceCategory.objects.create(service_point=point, **data)
    except IntegrityError as exc:
        raise ConflictError(
            "На этой точке уже есть категория с таким названием",
            code="category_exists",
        ) from exc


@transaction.atomic
def update_category(staff, category_id, **fields) -> ServiceCategory:
    category = get_category(staff, category_id, lock=True)
    changed = [key for key in fields if key in CATEGORY_FIELDS]
    for key in changed:
        setattr(category, key, fields[key])
    if changed:
        try:
            with transaction.atomic():
                category.save(update_fields=[*changed, "updated_at"])
        except IntegrityError as exc:
            raise ConflictError(
                "На этой точке уже есть категория с таким названием",
                code="category_exists",
            ) from exc
    return category


def _check_price(price, material_price) -> None:
    """Материал — часть цены, а не добавка к ней.

    Проверяем до базы: ограничение там есть, но его сообщение клиенту не
    покажешь, а мастер должен понять, что он ввёл не то.
    """
    if material_price is not None and price is not None and material_price > price:
        raise ValidationError(
            "Материал не может стоить больше услуги", code="material_above_price"
        )


@transaction.atomic
def create_service(staff, *, category, **fields) -> Service:
    parent = get_category(staff, category)
    data = {key: value for key, value in fields.items() if key in SERVICE_FIELDS}
    _check_price(data.get("price"), data.get("material_price"))
    try:
        with transaction.atomic():
            return Service.objects.create(category=parent, **data)
    except IntegrityError as exc:
        raise ConflictError(
            "В этой категории уже есть услуга с таким названием",
            code="service_exists",
        ) from exc


@transaction.atomic
def update_service(staff, service_id, **fields) -> Service:
    """Правка услуги: цена, остаток, «включена в работу».

    Остаток — абсолютное число, а не приращение: мастер пересчитывает
    полку и вводит то, что видит. «Плюс N» при двойном нажатии задвоил бы
    приход.
    """
    service = get_service(staff, service_id, lock=True)
    changed = [key for key in fields if key in SERVICE_FIELDS]
    for key in changed:
        setattr(service, key, fields[key])
    _check_price(service.price, service.material_price)
    if changed:
        try:
            with transaction.atomic():
                service.save(update_fields=[*changed, "updated_at"])
        except IntegrityError as exc:
            raise ConflictError(
                "В этой категории уже есть услуга с таким названием",
                code="service_exists",
            ) from exc
    return service
