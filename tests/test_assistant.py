"""Подсказчик в записи: выбор только из каталога, без цен, с лимитами и бюджетом."""

from __future__ import annotations

import io
import json
import urllib.error
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.assistant.models import AssistantRequest
from apps.assistant.providers import AssistantProviderError, Completion, get_provider
from apps.assistant.providers.base import AssistantProvider
from apps.assistant.providers.yandex import YandexGptProvider
from apps.assistant.services import assistant as assistant_service
from apps.catalog.models import Service, ServiceCategory

pytestmark = pytest.mark.django_db(transaction=True)

URL = reverse("v1:assistant:assistant")


class Stub(AssistantProvider):
    """Модель, которая отвечает заданным текстом и запоминает, что ей прислали."""

    name = "stub"

    def __init__(self, answer=None, *, text=None, error=False, filtered=False):
        self.text = text if text is not None else json.dumps(answer or {}, ensure_ascii=False)
        self.error = error
        self.filtered = filtered
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system, messages, schema):
        self.calls.append((system, messages))
        if self.error:
            raise AssistantProviderError("нет связи")
        return Completion(self.text, 1000, 500, "stub-model", filtered=self.filtered)


def answer(reply="Подойдёт замена масла.", category="", service="", on_site=False):
    return {"reply": reply, "category": category, "service": service, "on_site": on_site}


@pytest.fixture
def stub(monkeypatch):
    def _use(provider):
        monkeypatch.setattr(assistant_service, "get_provider", lambda: provider)
        return provider

    return _use


def ask(api, point, message="Пора менять масло", **extra):
    body = {"service_point": str(point.pk), "message": message, **extra}
    return api.post(URL, body, format="json")


# ----------------------------------------------------------------- подсказка
def test_suggests_a_service_of_the_point(auth, client_user, point, service, stub):
    stub(Stub(answer(service="U1")))

    body = ask(auth(client_user), point).json()

    assert body["service"] == {"id": str(service.pk), "name": service.name}
    assert body["category"]["id"] == str(service.category_id)
    assert body["on_site"] is False
    assert body["handoff"] == ""
    assert body["messages_left"] == 4


def test_model_sees_the_catalog_without_prices(auth, client_user, point, service, stub):
    provider = stub(Stub(answer()))

    ask(auth(client_user), point)

    system, messages = provider.calls[0]
    assert service.name in system and "K1 — Замена масла" in system
    for price in ("4800", "3900", "900"):
        assert price not in system
    assert messages == [{"role": "user", "text": "Пора менять масло"}]


def test_answer_has_no_prices(auth, client_user, point, service, stub):
    stub(Stub(answer(service="U1")))

    raw = ask(auth(client_user), point).content.decode()

    assert "price" not in raw and "4800" not in raw


def test_invented_service_is_dropped(auth, client_user, point, service, stub):
    stub(Stub(answer(service="U99", category="K7")))

    body = ask(auth(client_user), point).json()

    assert body["service"] is None and body["category"] is None


def test_on_site_only_where_the_category_allows_it(auth, client_user, point, service, stub):
    wash = ServiceCategory.objects.create(service_point=point, name="Мойка", allow_on_site=False)
    Service.objects.create(category=wash, name="Мойка кузова", price=Decimal("600"))
    api = auth(client_user)

    stub(Stub(answer(category="K1", on_site=True)))
    oil = ask(api, point).json()
    stub(Stub(answer(category="K2", on_site=True)))
    washing = ask(api, point).json()

    assert oil["on_site"] is True and oil["category"]["name"] == "Замена масла"
    assert washing["on_site"] is False and washing["category"]["name"] == "Мойка"


def test_a_price_in_the_reply_is_replaced(auth, client_user, point, service, stub):
    stub(Stub(answer(reply="Замена масла стоит 4 800 руб.", service="U1")))

    body = ask(auth(client_user), point).json()

    assert body["reply"] == assistant_service.SAFE_REPLY
    assert body["service"]["id"] == str(service.pk)


FENCED = '```json\n{"reply": "Вот", "service": "U1", "category": "", "on_site": false}\n```'


@pytest.mark.parametrize(
    ("text", "reply", "has_service"),
    [
        ("Уточните, пожалуйста, какой пробег?", "Уточните, пожалуйста, какой пробег?", False),
        (FENCED, "Вот", True),
        ("{сломанный json", assistant_service.NOT_UNDERSTOOD, False),
    ],
)
def test_answers_that_are_not_clean_json(
    auth, client_user, point, service, stub, text, reply, has_service
):
    stub(Stub(text=text))

    body = ask(auth(client_user), point).json()

    assert body["reply"] == reply
    assert (body["service"] is not None) is has_service


def test_phone_numbers_do_not_reach_the_model(auth, client_user, point, service, stub):
    provider = stub(Stub(answer()))

    ask(auth(client_user), point, message="Перезвоните на +7 900 111-22-33, стучит подвеска")

    text = provider.calls[0][1][-1]["text"]
    assert "111" not in text and "[номер]" in text


def test_history_goes_to_the_model_but_is_capped(auth, client_user, point, service, stub):
    provider = stub(Stub(answer()))
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "text": f"реплика {i}"}
        for i in range(20)
    ]

    ask(auth(client_user), point, history=history)

    messages = provider.calls[0][1]
    assert len(messages) == 9  # 4 прошлых пары + новое сообщение
    assert messages[0]["text"] == "реплика 12"


def test_filtered_answer_gives_no_suggestion(auth, client_user, point, service, stub):
    stub(Stub(answer(service="U1"), filtered=True))

    body = ask(auth(client_user), point).json()

    assert body["service"] is None
    assert body["reply"] == assistant_service.NOT_UNDERSTOOD


# ---------------------------------------------------------------- лимиты
def test_chat_ends_with_the_master_after_five_messages(auth, client_user, point, service, stub):
    provider = stub(Stub(answer(service="U1")))
    api = auth(client_user)
    chat = ask(api, point).json()["chat"]
    for _ in range(3):
        ask(api, point, chat=chat)

    fifth = ask(api, point, chat=chat).json()
    sixth = ask(api, point, chat=chat).json()

    assert fifth["handoff"] == "chat_limit" and fifth["messages_left"] == 0
    assert fifth["service"] is not None  # последний ответ — всё ещё ответ
    assert sixth["handoff"] == "chat_limit" and sixth["service"] is None
    assert len(provider.calls) == 5  # шестое в модель не ушло


def test_ten_messages_a_day_across_chats(auth, client_user, point, service, stub):
    provider = stub(Stub(answer()))
    api = auth(client_user)
    for _ in range(10):
        ask(api, point)  # каждый раз новый разговор

    body = ask(api, point).json()

    assert body["handoff"] == "daily_limit"
    assert len(provider.calls) == 10
    assert api.get(URL, {"service_point": str(point.pk)}).json()["available"] is False


def test_monthly_budget_hides_the_assistant(auth, client_user, other_user, point, service, stub):
    provider = stub(Stub(answer()))
    AssistantRequest.objects.create(
        user=other_user, service_point=point, chat="00000000-0000-0000-0000-000000000001",
        provider="stub", cost=Decimal("1000"),
    )
    api = auth(client_user)

    assert api.get(URL, {"service_point": str(point.pk)}).json()["available"] is False
    assert ask(api, point).json()["handoff"] == "budget"
    assert provider.calls == []


def test_cost_is_counted_by_the_tariff(auth, client_user, point, service, stub):
    stub(Stub(answer()))  # 1000 токенов на входе, 500 на выходе

    ask(auth(client_user), point)

    record = AssistantRequest.objects.get()
    assert record.cost == Decimal("0.3")  # 1000 × 0,20 + 500 × 0,20 за тысячу
    assert (record.input_tokens, record.output_tokens, record.model) == (1000, 500, "stub-model")


def test_provider_failure_hands_over_and_is_not_counted(auth, client_user, point, service, stub):
    stub(Stub(error=True))
    api = auth(client_user)

    body = ask(api, point).json()

    assert body["handoff"] == "unavailable" and body["phone"]
    assert AssistantRequest.objects.get().error == "provider"
    stub(Stub(answer()))
    assert api.get(URL, {"service_point": str(point.pk)}).json()["messages_left_today"] == 10


def test_suggestion_is_recorded_without_text(auth, client_user, point, service, stub):
    stub(Stub(answer(service="U1")))

    ask(auth(client_user), point, message="Мне бы масло поменять")

    record = AssistantRequest.objects.get()
    assert record.service == service and record.category == service.category
    texts = [str(value) for value in record.__dict__.values()]
    assert not any("масло поменять" in value for value in texts)


# ------------------------------------------------------------ запреты и вход
def test_switched_off_assistant(auth, client_user, point, settings):
    settings.ASSISTANT = {**settings.ASSISTANT, "PROVIDER": "off"}
    api = auth(client_user)

    assert api.get(URL, {"service_point": str(point.pk)}).json()["available"] is False
    response = ask(api, point)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "assistant_off"


@pytest.mark.parametrize(
    ("message", "code"),
    [("   ", "assistant_message_empty"), ("а" * 501, "assistant_message_too_long")],
)
def test_message_must_be_meaningful(auth, client_user, point, stub, message, code):
    stub(Stub(answer()))

    response = ask(auth(client_user), point, message=message)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


def test_unknown_point(auth, client_user, stub):
    stub(Stub(answer()))
    response = auth(client_user).post(
        URL,
        {"service_point": "00000000-0000-0000-0000-000000000000", "message": "масло"},
        format="json",
    )

    assert response.status_code == 404


def test_only_clients(api, auth, master_user, point):
    assert ask(api, point).status_code == 401
    assert ask(auth(master_user), point).status_code == 403


# ---------------------------------------------------------------- YandexGPT
class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _yandex(settings):
    settings.ASSISTANT = {
        **settings.ASSISTANT, "PROVIDER": "yandex",
        "YANDEX_API_KEY": "test-key", "YANDEX_FOLDER_ID": "b1folder",
    }
    return YandexGptProvider()


OK_BODY = {
    "result": {
        "alternatives": [{"message": {"role": "assistant", "text": '{"reply": "Да"}'},
                          "status": "ALTERNATIVE_STATUS_FINAL"}],
        "usage": {"inputTextTokens": "812", "completionTokens": "27", "totalTokens": "839"},
        "modelVersion": "23.10.2024",
    }
}


def test_yandex_request_and_response(settings, monkeypatch):
    provider = _yandex(settings)
    sent = []

    def urlopen(request, timeout):
        sent.append(request)
        return _Response(json.dumps(OK_BODY).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    messages = [{"role": "user", "text": "масло"}]
    completion = provider.complete("правила", messages, {"type": "object"})

    body = json.loads(sent[0].data)
    assert sent[0].get_header("Authorization") == "Api-Key test-key"
    assert body["modelUri"] == "gpt://b1folder/yandexgpt-lite/latest"
    assert body["messages"][0] == {"role": "system", "text": "правила"}
    assert body["jsonSchema"] == {"schema": {"type": "object"}}
    assert (completion.input_tokens, completion.output_tokens) == (812, 27)
    assert completion.text == '{"reply": "Да"}' and not completion.filtered


def test_yandex_retries_without_json_schema_on_400(settings, monkeypatch):
    provider = _yandex(settings)
    sent = []

    def urlopen(request, timeout):
        sent.append(json.loads(request.data))
        if len(sent) == 1:
            raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, io.BytesIO(b"{}"))
        return _Response(json.dumps(OK_BODY).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    provider.complete("правила", [{"role": "user", "text": "масло"}], {"type": "object"})

    assert "jsonSchema" in sent[0] and "jsonSchema" not in sent[1]


def test_yandex_failure_is_a_provider_error(settings, monkeypatch):
    provider = _yandex(settings)

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "quota", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    with pytest.raises(AssistantProviderError):
        provider.complete("правила", [{"role": "user", "text": "масло"}], {})


def test_yandex_without_keys_means_switched_off(settings):
    settings.ASSISTANT = {**settings.ASSISTANT, "PROVIDER": "yandex", "YANDEX_API_KEY": ""}

    assert get_provider() is None


def test_fake_provider_suggests_the_first_service(auth, client_user, point, service):
    body = ask(auth(client_user), point).json()

    assert body["service"]["id"] == str(service.pk)
