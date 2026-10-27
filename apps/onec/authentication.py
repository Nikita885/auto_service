"""Вход 1С по ключу обмена.

Не JWT сотрудника: обмен идёт регламентным заданием на сервере 1С, без
человека за клавиатурой, а токен входа живёт час и требует пароля для
обновления. Ключ лежит в `.env` сайта и в настройках обработки в 1С;
поменять его — значит отключить старую 1С сразу, без ожидания.
"""

from __future__ import annotations

import hmac

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from apps.common.exceptions import UnavailableError
from apps.onec.services import sync as sync_service

KEYWORD = "OneC"


class OneCKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        prefix = f"{KEYWORD} "
        if not header.startswith(prefix):
            return None

        expected = settings.ONEC["API_KEY"]
        if not sync_service.key_is_usable(expected):
            raise UnavailableError(
                "Обмен с 1С на сайте выключен (ONEC_API_KEY)", code="onec_disabled"
            )
        # Сравнение за постоянное время: по времени ответа ключ не угадать.
        if not hmac.compare_digest(header[len(prefix):].strip().encode(), expected.encode()):
            raise AuthenticationFailed("Неверный ключ обмена 1С", code="onec_bad_key")
        return sync_service.actor(), KEYWORD

    def authenticate_header(self, request) -> str:
        return KEYWORD


class IsOneC(BasePermission):
    """Только запрос с ключом 1С: JWT сотрудника сюда не пускает.

    Иначе любой мастер из панели мог бы подтвердить выгрузку за 1С, и
    записи пропали бы из обмена, так и не попав в заявки.
    """

    message = "Доступно только обмену с 1С."

    def has_permission(self, request, view) -> bool:
        return request.auth == KEYWORD
