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
from apps.booking.models import Booking
from apps.booking.services import booking as booking_service
from apps.booking.services import slots as slots_service
from apps.booking.services import stock as stock_service
from apps.catalog.models import ServicePoint
from apps.common.exceptions import ConflictError, NotFoundError, PermissionError_
from apps.common.phone import mask_phone

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


@transaction.atomic
def book(
    master,
    *,
    phone: str,
    full_name: str,
    car_model: str = "",
    car_plate: str = "",
    service_point_id,
    oil_id,
    start_at: datetime,
    comment: str = "",
) -> Booking:
    """Записать клиента. Нет аккаунта с таким номером — он заводится."""
    # Блокировка точки ставит в очередь и подтверждения черновиков, и
    # записи мастеров на неё: последний пост не достанется двоим.
    point = point_for_master(master, service_point_id, lock=True)
    start_at, end_at = slots_service.validate_slot(point, start_at, walk_in=True)
    oil = stock_service.get_available_oil(point, oil_id)

    user, created = accounts_services.get_or_create_client(
        phone, full_name=full_name, car_model=car_model, car_plate=car_plate
    )
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
