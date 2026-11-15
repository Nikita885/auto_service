"""JWT-аутентификация для WebSocket.

Браузерный WebSocket не умеет слать кастомные заголовки, поэтому токен
принимаем в query-строке: `ws://host/ws/booking/?token=<access>`.
Мобильные клиенты могут слать его же — единый контракт.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _get_user_from_token(raw_token: str):
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    try:
        token = AccessToken(raw_token)
    except TokenError:
        return AnonymousUser(), None

    user_model = get_user_model()
    try:
        user = user_model.objects.get(id=token["user_id"])
    except (user_model.DoesNotExist, KeyError):
        return AnonymousUser(), None

    return (user, int(token["exp"])) if user.is_active else (AnonymousUser(), None)


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get("query_string", b"").decode())
        raw_token = (query.get("token") or [None])[0]

        scope["user"], scope["token_exp"] = (
            await _get_user_from_token(raw_token) if raw_token else (AnonymousUser(), None)
        )
        return await super().__call__(scope, receive, send)


class LiveAccessMixin:
    """Перепроверяет доступ до каждого события и закрывает протухшие JWT."""

    def watch_access(self):
        self._access_task = asyncio.create_task(self._watch_access())

    async def _watch_access(self):
        try:
            while True:
                remaining = self.scope.get("token_exp", 0) - time.time()
                await asyncio.sleep(max(0, min(15, remaining)))
                if not await self.access_allowed():
                    return
        except asyncio.CancelledError:
            return

    def stop_access_watch(self):
        task = getattr(self, "_access_task", None)
        if task:
            task.cancel()

    async def access_allowed(self):
        if self.scope.get("token_exp", 0) <= time.time() or not await self._current_access():
            await self.close(code=4401)
            return False
        return True

    @database_sync_to_async
    def _current_access(self):
        user = get_user_model().objects.filter(pk=self.scope["user"].pk, is_active=True).first()
        if not user:
            return False
        if hasattr(self, "point_ids"):
            if user.role not in ("master", "admin"):
                return False
            from apps.catalog.models import ServicePoint

            points = ServicePoint.objects.filter(is_active=True)
            allowed = user.accessible_point_ids()
            if allowed is not None:
                points = points.filter(pk__in=allowed)
            return set(points.values_list("pk", flat=True)) == set(self.point_ids)
        return user.role == self.scope["user"].role
