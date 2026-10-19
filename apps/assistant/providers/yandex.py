"""YandexGPT через Text Generation API Yandex AI Studio.

Один синхронный POST на `foundationModels/v1/completion`. Как и у SMS-шлюзов,
HTTP-клиент — `urllib` из стандартной библиотеки: тащить зависимость ради
одного запроса незачем.

Авторизация — API-ключ сервисного аккаунта с ролью
`ai.languageModels.user`; модель адресуется URI `gpt://<каталог>/<модель>`.
Ответ просим в формате JSON Schema (`jsonSchema`). Если модель этот режим
не принимает (400), повторяем без него: формат ответа описан и в промпте,
а разбирает и проверяет его всё равно сервис подсказчика.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from apps.assistant.providers.base import AssistantProvider, AssistantProviderError, Completion

logger = logging.getLogger(__name__)

URL = "https://ai.api.cloud.yandex.net/foundationModels/v1/completion"
FILTERED = "ALTERNATIVE_STATUS_CONTENT_FILTER"


class YandexGptProvider(AssistantProvider):
    name = "yandex"

    def __init__(self) -> None:
        conf = settings.ASSISTANT
        self.api_key = conf["YANDEX_API_KEY"]
        self.folder_id = conf["YANDEX_FOLDER_ID"]
        self.model = conf["YANDEX_MODEL"]
        self.timeout = conf["TIMEOUT_SECONDS"]
        if not self.api_key or not self.folder_id:
            raise AssistantProviderError(
                "Не заданы ASSISTANT_YANDEX_API_KEY и ASSISTANT_YANDEX_FOLDER_ID"
            )

    def _body(self, system: str, messages: list[dict], schema: dict | None) -> dict:
        body = {
            "modelUri": f"gpt://{self.folder_id}/{self.model}",
            "completionOptions": {
                "stream": False,
                # Низкая температура: нужен выбор из списка, а не фантазия.
                "temperature": 0.2,
                "maxTokens": "400",
            },
            "messages": [{"role": "system", "text": system}]
            + [{"role": m["role"], "text": m["text"]} for m in messages],
        }
        if schema is not None:
            body["jsonSchema"] = {"schema": schema}
        return body

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Api-Key {self.api_key}",
                "x-folder-id": self.folder_id,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def complete(self, system: str, messages: list[dict], schema: dict) -> Completion:
        try:
            try:
                data = self._post(self._body(system, messages, schema))
            except urllib.error.HTTPError as exc:
                if exc.code != 400:
                    raise
                logger.warning("YandexGPT не принял jsonSchema (400), повторяем без неё")
                data = self._post(self._body(system, messages, None))
        except urllib.error.HTTPError as exc:
            # Тело ошибки — в лог: там причина (ключ, квота, модель), а
            # ключа в нём нет — он уходит только в заголовке.
            detail = exc.read().decode("utf-8", "replace")[:500]
            logger.error("YandexGPT ответил %s: %s", exc.code, detail)
            raise AssistantProviderError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            logger.error("YandexGPT недоступен: %s", exc)
            raise AssistantProviderError(str(exc)) from exc

        # REST-шлюз оборачивает ответ в "result"; на всякий случай читаем и без него.
        result = data.get("result", data)
        try:
            alternative = result["alternatives"][0]
            usage = result.get("usage", {})
            return Completion(
                text=alternative.get("message", {}).get("text", ""),
                # int64 в JSON gRPC-шлюза приходит строкой.
                input_tokens=int(usage.get("inputTextTokens", 0)),
                output_tokens=int(usage.get("completionTokens", 0)),
                model=result.get("modelVersion", "") or self.model,
                filtered=alternative.get("status") == FILTERED,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.error("Непонятный ответ YandexGPT: %.500s", data)
            raise AssistantProviderError("непонятный ответ") from exc
