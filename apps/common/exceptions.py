"""Доменные исключения и единый формат ошибки API.

Сервисный слой не знает про HTTP — он бросает доменные исключения.
Превращение их в HTTP-ответ происходит ровно в одном месте: в
`api_exception_handler`. Благодаря этому одну и ту же бизнес-логику можно
дёргать из вьюхи, из Celery-задачи и из management-команды.

Формат ответа всегда один и тот же, чтобы мобильному клиенту было
удобно разбирать ошибки по машиночитаемому `code`:

    {"error": {"code": "slot_taken", "message": "...", "details": {}}}
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Базовая ошибка бизнес-логики."""

    code = "domain_error"
    message = "Ошибка бизнес-логики"
    http_status = status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(DomainError):
    code = "validation_error"
    message = "Некорректные данные"
    http_status = status.HTTP_400_BAD_REQUEST


class NotFoundError(DomainError):
    code = "not_found"
    message = "Объект не найден"
    http_status = status.HTTP_404_NOT_FOUND


class PermissionError_(DomainError):
    code = "permission_denied"
    message = "Недостаточно прав"
    http_status = status.HTTP_403_FORBIDDEN


class ConflictError(DomainError):
    """Состояние изменилось под нами: слот заняли, масло кончилось и т. п."""

    code = "conflict"
    message = "Конфликт состояния"
    http_status = status.HTTP_409_CONFLICT


class GoneError(DomainError):
    """Ресурс был, но протух. Основной кейс — истёкший черновик записи."""

    code = "gone"
    message = "Ресурс больше не доступен"
    http_status = status.HTTP_410_GONE


class RateLimitError(DomainError):
    code = "rate_limited"
    message = "Слишком много запросов"
    http_status = status.HTTP_429_TOO_MANY_REQUESTS


def _envelope(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Единая точка превращения исключения в HTTP-ответ."""

    if isinstance(exc, DomainError):
        logger.info("domain error: %s (%s)", exc.code, exc.message)
        return Response(
            _envelope(exc.code, exc.message, exc.details), status=exc.http_status
        )

    if isinstance(exc, Http404):
        return Response(
            _envelope("not_found", "Объект не найден"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, DjangoPermissionDenied):
        return Response(
            _envelope("permission_denied", "Недостаточно прав"),
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, DjangoValidationError):
        return Response(
            _envelope(
                "validation_error",
                "Некорректные данные",
                {"fields": getattr(exc, "message_dict", {"__all__": exc.messages})},
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail:
        code = getattr(detail["detail"], "code", "error")
        return Response(_envelope(str(code), str(detail["detail"])), status=response.status_code)

    # Ошибки валидации сериализаторов: {"field": ["сообщение"]}
    return Response(
        _envelope("validation_error", "Некорректные данные", {"fields": detail}),
        status=response.status_code,
    )
