"""Публикация событий записи в WebSocket.

Каналов два, и они устроены по-разному.

**Клиент** слушает свою личную группу `user.<uuid>` и получает полное
состояние — и тик черновика, и смену статуса брони.

**Сотрудник** слушает группы точек `staff.point.<uuid>` и получает только
*сигнал*: что-то изменилось у такой-то записи. Полные данные он забирает
обычным REST-запросом со своими фильтрами. Так сделано по двум причинам:

1. Слои остаются чистыми. Мастерские сериализаторы живут в `apps.master`,
   который зависит от `apps.booking`; тянуть их отсюда — замкнуть зависимость.
2. У мастера на экране фильтры (дата, статус, точка, поиск). Вставлять
   пришедшую строку в список пришлось бы, повторив логику фильтрации на
   клиенте, — а это верный способ однажды показать запись, которая под
   фильтр не подходит.

Падение Redis не должно ронять бизнес-операцию, поэтому любые ошибки здесь
только логируются.
"""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

# Типы событий — общий контракт с мобильным клиентом.
DRAFT_UPDATED = "draft.updated"
DRAFT_EXPIRED = "draft.expired"
DRAFT_CLOSED = "draft.closed"
BOOKING_CREATED = "booking.created"
BOOKING_UPDATED = "booking.updated"
BOOKING_CANCELLED = "booking.cancelled"


def user_group(user_id) -> str:
    return f"user.{user_id}"


def point_group(point_id) -> str:
    """Группа сотрудников одной точки обслуживания."""
    return f"staff.point.{point_id}"


def _send(group: str, event: str, payload: dict[str, Any] | None) -> None:
    layer = get_channel_layer()
    if layer is None:  # pragma: no cover - только если channels не настроены
        return

    try:
        async_to_sync(layer.group_send)(
            group,
            {"type": "stream.event", "event": event, "payload": payload},
        )
    except Exception:  # pragma: no cover - инфраструктурный сбой
        logger.exception("Не удалось отправить событие %s в %s", event, group)


def publish(user_id, event: str, payload: dict[str, Any]) -> None:
    _send(user_group(user_id), event, payload)


def publish_draft(draft, event: str = DRAFT_UPDATED) -> None:
    from apps.booking.serializers import BookingDraftSerializer

    publish(draft.user_id, event, BookingDraftSerializer(draft).data)

    # Пока адрес не выбран, черновик не относится ни к одной точке —
    # и сообщать о нём некому.
    if draft.service_point_id:
        _send(
            point_group(draft.service_point_id),
            event,
            {
                "draft_id": str(draft.id),
                "service_point_id": str(draft.service_point_id),
                "is_open": draft.is_open,
            },
        )


def publish_booking(booking, event: str = BOOKING_UPDATED) -> None:
    from apps.booking.serializers import BookingSerializer

    publish(booking.user_id, event, BookingSerializer(booking).data)

    _send(
        point_group(booking.service_point_id),
        event,
        {
            "booking_id": str(booking.id),
            "service_point_id": str(booking.service_point_id),
            "code": booking.code,
            "status": booking.status,
            "start_at": booking.start_at.isoformat(),
            # Время точки, а не сервера и не браузера: у сети адреса могут
            # оказаться в разных часовых поясах.
            "local_time": booking.local_start().strftime("%d.%m.%Y %H:%M"),
        },
    )
