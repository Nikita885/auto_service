from __future__ import annotations

import logging

from django.conf import settings

from apps.assistant.providers.base import (
    AssistantProvider,
    AssistantProviderError,
    Completion,
)
from apps.assistant.providers.fake import FakeProvider
from apps.assistant.providers.yandex import YandexGptProvider

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, type[AssistantProvider]] = {
    "yandex": YandexGptProvider,
    "fake": FakeProvider,
}


def get_provider() -> AssistantProvider | None:
    """Провайдер из настроек, или None — подсказчик выключен.

    Неверная настройка (нет ключа, неизвестное имя) — тоже «выключен», а не
    500 на экране записи: запись должна работать и без подсказчика. Причина
    уходит в лог. Без кеша: настройки читаются раз на запрос, а объект
    провайдера ничего тяжёлого не держит.
    """
    name = settings.ASSISTANT["PROVIDER"]
    if name == "off":
        return None
    try:
        return PROVIDERS[name]()
    except KeyError:
        logger.error("Неизвестный провайдер подсказчика: %s", name)
    except AssistantProviderError as exc:
        logger.error("Подсказчик не настроен: %s", exc)
    return None


__all__ = [
    "AssistantProvider",
    "AssistantProviderError",
    "Completion",
    "PROVIDERS",
    "get_provider",
]
