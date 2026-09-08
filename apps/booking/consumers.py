"""WebSocket-канал состояния записи.

`ws://<host>/ws/booking/?token=<access JWT>`

Сразу после подключения клиент получает снимок текущего черновика (или
`draft.absent`), дальше — события по мере изменений. Это и есть «статус в
реальном времени»: отдельный поллинг не нужен, хотя REST-эндпоинт
`/bookings/drafts/current/` остаётся как запасной вариант.
"""

from __future__ import annotations

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.booking import events

logger = logging.getLogger(__name__)


class BookingStreamConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)  # Unauthorized
            return

        self.group = events.user_group(user.id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

        snapshot = await self._draft_snapshot(user)
        if snapshot is None:
            await self.send_json({"event": "draft.absent", "payload": None})
        else:
            await self.send_json({"event": events.DRAFT_UPDATED, "payload": snapshot})

    async def disconnect(self, code) -> None:
        group = getattr(self, "group", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs) -> None:
        """Канал односторонний. Отвечаем только на ping, чтобы держать соединение."""
        if content.get("action") == "ping":
            await self.send_json({"event": "pong"})

    async def stream_event(self, message) -> None:
        await self.send_json(
            {"event": message["event"], "payload": message["payload"]}
        )

    @database_sync_to_async
    def _draft_snapshot(self, user):
        from apps.booking.serializers import BookingDraftSerializer
        from apps.booking.services import draft as draft_service

        draft = draft_service.get_open_draft(user)
        return BookingDraftSerializer(draft).data if draft else None
