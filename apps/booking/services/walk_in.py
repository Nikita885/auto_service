"""Запись клиента мастером: позвонил или приехал без записи.

Проверки те же, что у клиента в приложении, и из тех же модулей
(`slots`, `stock`): свободный пост, масло на полке, горизонт записи,
нет ли у клиента другой записи на это время. Отличие одно — нет
минимального запаса до начала: мастер записывает и в слот, который уже
идёт, если пост свободен (живая очередь).

Черновика нет: пятиминутный таймер держит слот, пока клиент думает в
приложении, а мастер вводит всё одним окном и подтверждает сразу.
Гонку с клиентами из приложения закрывает та же блокировка строки точки,
что и при подтверждении черновика.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.db import transaction

from apps.accounts import services as accounts_services
from apps.accounts.constants import UserRole
from apps.booking.models import Booking
from apps.booking.services import booking as booking_service
from apps.booking.services import slots as slots_service
from apps.booking.services import stock as stock_service
from apps.catalog.models import ServicePoint
from apps.common.exceptions import ConflictError, NotFoundError, PermissionError_
from apps.common.phone import mask_phone, normalize_phone
from apps.garage.services import cars as cars_service

logger = logging.getLogger(__name__)

LOG_COMMENT = "Запись создана мастером"


def point_for_master(master, point_id, *, lock: bool = False) -> ServicePoint:
    """Действующая точка, на которую этому сотруднику можно записывать."""
    qs = ServicePoint.objects.filter(is_active=True)
    if lock:
        qs = qs.select_for_update()
    try:
        point = qs.get(pk=point_id)
    except (ServicePoint.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Точка не найдена", code="point_not_found") from exc

    allowed = master.accessible_point_ids()
    if allowed is not None and point.pk not in allowed:
        raise PermissionError_("Это не ваша точка", code="point_not_allowed")
    return point


def lookup(raw_phone: str) -> dict:
    """Кто стоит за номером: имя и машины для окна «Записать клиента»."""
    phone = normalize_phone(raw_phone)
    user = accounts_services.find_client(phone)
    is_client = user is None or user.role == UserRole.CLIENT
    cars = list(cars_service.list_cars(user)) if user is not None and is_client else []
    primary = next((car for car in cars if car.is_primary), None)
    return {
        "phone": phone,
        "found": user is not None,
        "is_client": is_client,
        "full_name": user.full_name if user is not None and is_client else "",
        "car_model": primary.title if primary else "",
        "car_plate": primary.plate if primary else "",
        "cars": cars,
    }


@transaction.atomic
def book(
    master,
    *,
    phone: str,
    full_name: str,
    car_model: str = "",
    car_plate: str = "",
    car_id=None,
    service_point_id,
    oil_id,
    start_at: datetime,
    comment: str = "",
) -> Booking:
    """Записать клиента. Нет аккаунта с таким номером — он заводится.

    Машина: `car_id` — одна из машин этого клиента (выбрана в окне из
    подсказки); иначе названная мастером ищется среди машин клиента по
    номеру и названию и добавляется, если её нет; не названа — основная.
    """
    # Блокировка точки ставит в очередь и подтверждения черновиков, и
    # записи мастеров на неё: последний пост не достанется двоим.
    point = point_for_master(master, service_point_id, lock=True)
    start_at, end_at = slots_service.validate_slot(point, start_at, walk_in=True)
    oil = stock_service.get_available_oil(point, oil_id)

    user, created = accounts_services.get_or_create_client(phone, full_name=full_name)
    if car_id:
        car = cars_service.get_car(user, car_id)
    else:
        car = cars_service.match_or_add(user, title=car_model, plate=car_plate)
    if car is not None:
        car_model, car_plate = cars_service.snapshot(car)
    if Booking.objects.active().filter(user=user, start_at=start_at).exists():
        raise ConflictError(
            "У клиента уже есть запись на это время", code="duplicate_booking"
        )

    booking = booking_service.create_booking(
        user=user,
        point=point,
        oil=oil,
        start_at=start_at,
        end_at=end_at,
        client_name=full_name,
        car=car,
        car_model=car_model,
        car_plate=car_plate,
        comment=comment,
        actor=master,
        log_comment=LOG_COMMENT,
    )
    logger.info(
        "Мастер записал %s (%s): %s",
        mask_phone(user.phone), "новый" if created else "есть в базе", booking.code,
    )
    return booking
