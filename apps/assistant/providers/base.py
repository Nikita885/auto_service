"""Контракт провайдера подсказчика.

Сервис подсказчика не знает, чья модель отвечает. Смена YandexGPT на
другую модель — соседний класс и строка `ASSISTANT_PROVIDER` в .env, как у
SMS-шлюзов: промпт, проверка ответа, лимиты и учёт трат остаются прежними.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


class AssistantProviderError(Exception):
    """Модель не ответила: сеть, ключ, квота, непонятный ответ.

    Клиенту это не ошибка, а «дальше поможет мастер»: запись работает и
    без подсказчика.
    """


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    # Ответ остановил фильтр провайдера — текста нет, подсказки тоже.
    filtered: bool = False


class AssistantProvider(abc.ABC):
    name = ""

    @abc.abstractmethod
    def complete(self, system: str, messages: list[dict], schema: dict) -> Completion:
        """Ответ модели на разговор.

        `messages` — [{"role": "user"|"assistant", "text": "..."}], последнее —
        от клиента. `schema` — JSON Schema ответа; провайдер передаёт её
        модели, если умеет, но разбор и проверка — у вызывающего.
        """
        raise NotImplementedError
