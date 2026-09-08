"""Контракт SMS-провайдера.

Прикладной код никогда не знает, кто именно шлёт сообщение. Смена шлюза —
это новый класс и одна строка в .env, а не правки в бизнес-логике.
"""

from __future__ import annotations

import abc


class SmsDeliveryError(Exception):
    """Провайдер не смог отправить сообщение. Повторяется задачей Celery."""


class SmsProvider(abc.ABC):
    @abc.abstractmethod
    def send(self, phone: str, text: str) -> str:
        """Отправить SMS. Возвращает id сообщения у провайдера."""
        raise NotImplementedError
