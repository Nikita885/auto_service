"""Провайдер для разработки: печатает SMS в лог вместо реальной отправки."""

from __future__ import annotations

import logging
import uuid

from apps.notifications.providers.base import SmsProvider

logger = logging.getLogger(__name__)


class ConsoleSmsProvider(SmsProvider):
    def send(self, phone: str, text: str) -> str:
        message_id = uuid.uuid4().hex
        logger.warning("[SMS -> %s] %s", phone, text)
        return message_id
