"""WebSocket-канал сотрудника.

`ws://<host>/ws/master/?token=<access JWT>`

Мастер подписывается на группы своих точек и сразу узнаёт, что появилась
новая запись, что клиент отменил бронь или что кто-то прямо сейчас
записывается. Сами данные он забирает REST-запросом со своими фильтрами —
по каналу приходит только сигнал (подробности в `apps/booking/events.py`).

Канал не заменяет REST, а ускоряет его: если WebSocket недоступен, панель
продолжает работать на обычных запросах.
"""

from __future__ import annotations

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.accounts.constants import UserRole
from apps.booking import events


class MasterStreamConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)  # Unauthorized
            return

        if user.role not in (UserRole.MASTER, UserRole.ADMIN):
            await self.close(code=4403)  # Forbidden — клиенту тут делать нечего
            return

        self.point_ids = await self._point_ids(user)
        self.joined = [events.point_group(pk) for pk in self.point_ids]

        for group in self.joined:
            await self.channel_layer.group_add(group, self.channel_name)

        await self.accept()
        # Сообщаем, за какими точками канал следит: панель по этому списку
        # понимает, что подписка живая и полная.
        await self.send_json(
            {
                "event": "master.ready",
                "payload": {"service_points": [str(pk) for pk in self.point_ids]},
            }
        )

    async def disconnect(self, code) -> None:
        for group in getattr(self, "joined", []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs) -> None:
        """Канал односторонний. Отвечаем только на ping, чтобы держать соединение."""
        if content.get("action") == "ping":
            await self.send_json({"event": "pong"})

    async def stream_event(self, message) -> None:
        await self.send_json({"event": message["event"], "payload": message["payload"]})

    @database_sync_to_async
    def _point_ids(self, user) -> list:
        """Точки, за которыми следит этот сотрудник.

        У мастера без привязки и у администратора это все активные точки:
        то же правило, что и в REST (`accessible_point_ids`), иначе доступ и
        подписка разъехались бы.
        """
        from apps.catalog.models import ServicePoint

        allowed = user.accessible_point_ids()
        qs = ServicePoint.objects.filter(is_active=True)
        if allowed is not None:
            qs = qs.filter(id__in=allowed)
        return list(qs.values_list("id", flat=True))
