"""Публикация событий записи в WebSocket.

Один канал на пользователя (`user.<uuid>`) — клиент подписывается один раз
и получает и тик черновика, и смену статуса брони. Падение Redis не должно
ронять бизнес-операцию, поэтому любые ошибки здесь только логируются.
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


def publish(user_id, event: str, payload: dict[str, Any]) -> None:
    layer = get_channel_layer()
    if layer is None:  # pragma: no cover - только если channels не настроены
        return

    try:
        async_to_sync(layer.group_send)(
            user_group(user_id),
            {"type": "stream.event", "event": event, "payload": payload},
        )
    except Exception:  # pragma: no cover - инфраструктурный сбой
        logger.exception("Не удалось отправить событие %s", event)


def publish_draft(draft, event: str = DRAFT_UPDATED) -> None:
    from apps.booking.serializers import BookingDraftSerializer

    publish(draft.user_id, event, BookingDraftSerializer(draft).data)


def publish_booking(booking, event: str = BOOKING_UPDATED) -> None:
    from apps.booking.serializers import BookingSerializer

    publish(booking.user_id, event, BookingSerializer(booking).data)
