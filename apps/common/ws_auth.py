"""JWT-аутентификация для WebSocket.

Браузерный WebSocket не умеет слать кастомные заголовки, поэтому токен
принимаем в query-строке: `ws://host/ws/booking/?token=<access>`.
Мобильные клиенты могут слать его же — единый контракт.
"""

from __future__ import annotations

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
        return AnonymousUser()

    user_model = get_user_model()
    try:
        user = user_model.objects.get(id=token["user_id"])
    except (user_model.DoesNotExist, KeyError):
        return AnonymousUser()

    return user if user.is_active else AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query = parse_qs(scope.get("query_string", b"").decode())
        raw_token = (query.get("token") or [None])[0]

        scope["user"] = (
            await _get_user_from_token(raw_token) if raw_token else AnonymousUser()
        )
        return await super().__call__(scope, receive, send)
