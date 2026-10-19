"""Подсказчик без сети — для разработки и тестов.

Предлагает первую услугу из каталога точки: так весь путь — кнопка,
разговор, «Выбрать», запись — проверяется без ключа и без трат.
"""

from __future__ import annotations

import json
import re

from apps.assistant.providers.base import AssistantProvider, Completion


class FakeProvider(AssistantProvider):
    name = "fake"

    def complete(self, system: str, messages: list[dict], schema: dict) -> Completion:
        service = re.search(r"^\s+(U\d+) — (.+?)(?::|$)", system, re.MULTILINE)
        category = re.search(r"^(K\d+) — ", system, re.MULTILINE)
        if service:
            answer = {
                "reply": f"Похоже, подойдёт «{service.group(2)}».",
                "category": "",
                "service": service.group(1),
                "on_site": False,
            }
        else:
            answer = {
                "reply": "Мастер подберёт услугу на месте.",
                "category": category.group(1) if category else "",
                "service": "",
                "on_site": bool(category),
            }
        text = json.dumps(answer, ensure_ascii=False)
        return Completion(
            text=text,
            input_tokens=len(system) // 3,
            output_tokens=len(text) // 3,
            model="fake",
        )
