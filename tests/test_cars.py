"""Справочник автомобилей и умный поиск по нему.

Каждая проверка здесь — это реальный способ, которым человек набирает
марку. Список собран не из головы: он вырос из прогона поиска по живому
справочнику, где половина запросов сначала не находила ничего.
"""

from __future__ import annotations

import pytest

from apps.catalog.models import CarMake, CarModel
from apps.catalog.services import cars
from apps.common.translit import normalize, search_index

pytestmark = pytest.mark.django_db

MAKES = "/api/v1/cars/makes/"
SEARCH = "/api/v1/cars/search/"


@pytest.fixture
def catalog(db):
    """Кусочек справочника: три марки, которых хватает на все случаи."""
    kia = CarMake.objects.create(name="Kia", search_terms="Киа, Кия", sort_order=1)
    mercedes = CarMake.objects.create(
        name="Mercedes-Benz",
        search_terms="Мерседес, Мерс, Мерин, Мерседес-Бенц",
        sort_order=2,
    )
    uaz = CarMake.objects.create(name="UAZ", search_terms="УАЗ, Патриот", sort_order=3)

    CarModel.objects.create(make=kia, name="Rio")
    CarModel.objects.create(make=kia, name="Sportage")
    CarModel.objects.create(make=mercedes, name="E-Class")
    CarModel.objects.create(make=uaz, name="Patriot")
    return {"kia": kia, "mercedes": mercedes, "uaz": uaz}


# ------------------------------------------------------- нормализация


@pytest.mark.parametrize(
    ("latin", "cyrillic"),
    [
        ("Lexus", "лексус"),
        ("Camry", "камри"),
        ("Toyota", "тойота"),
        ("Qashqai", "кашкай"),
        ("Granta", "гранта"),
        ("Logan", "логан"),
        ("Niva", "нива"),
    ],
)
def test_latin_and_cyrillic_spellings_meet(latin, cyrillic):
    """Два написания одного слова обязаны сойтись в одной форме — на этом
    держится весь поиск."""
    assert normalize(latin) == normalize(cyrillic)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("E-Class", "eklass"),
        ("e class", "eklass"),
        ("  Rio  ", "rio"),
        ("X5", "ks5"),
    ],
)
def test_normalize_drops_separators_and_case(value, expected):
    assert normalize(value) == expected


def test_index_keeps_both_glued_and_split_forms():
    """«Mercedes-Benz» набирают и слитно, и двумя словами. Какую форму
    выберет человек, заранее неизвестно, поэтому в индексе обе."""
    index = search_index("Mercedes-Benz")

    assert "merkedesbenz" in index
    assert "merkedes" in index
    assert "benz" in index


def test_index_does_not_glue_separate_terms():
    """Иначе «Kia» плюс «Rio» находились бы по запросу «ари»."""
    index = search_index("Kia", "Rio")

    assert index == "kia rio"


# ------------------------------------------------------- поиск марок


@pytest.mark.parametrize("query", ["мерс", "merc", "Мерседес", "мерседес бенц", "МЕРС"])
def test_make_is_found_by_any_spelling(catalog, query):
    found = [make.name for make in cars.search_makes(query)]

    assert found == ["Mercedes-Benz"]


def test_make_search_matches_only_word_beginnings(catalog):
    """«рио» не должно выдавать UAZ: «rio» сидит внутри «patriot», но
    человек набирает начало слова, а не его середину."""
    found = [make.name for make in cars.search_makes("рио")]

    assert found == []


def test_make_search_requires_every_word(catalog):
    assert [m.name for m in cars.search_makes("мерседес бенц")] == ["Mercedes-Benz"]
    assert list(cars.search_makes("мерседес киа")) == []


def test_empty_query_returns_list_in_catalog_order(catalog):
    """Открыв выбор марки, человек видит ходовые сверху, а не Acura с
    Alfa Romeo, как было бы по алфавиту."""
    found = [make.name for make in cars.search_makes("")]

    assert found == ["Kia", "Mercedes-Benz", "UAZ"]


def test_hidden_makes_are_not_suggested(catalog):
    catalog["uaz"].is_active = False
    catalog["uaz"].save()

    assert "UAZ" not in [make.name for make in cars.search_makes("уаз")]


# ------------------------------------------------------ поиск моделей


def test_model_search_within_make(catalog):
    found = [model.name for model in cars.search_models(catalog["kia"], "рио")]

    assert found == ["Rio"]


@pytest.mark.parametrize("query", ["kia rio", "киа рио", "кия рио", "рио киа", "рио"])
def test_model_is_found_together_with_its_make(catalog, query):
    """Человек набирает марку и модель одной строкой, не задумываясь, что
    это два справочника. Порядок слов при этом любой."""
    found = [str(model) for model in cars.search_everything(query)]

    assert found == ["Kia Rio"]


def test_model_inherits_make_synonyms(catalog):
    """«кия рио» обязано работать так же, как «kia rio»: синонимы марки
    входят в индекс модели."""
    assert [str(m) for m in cars.search_everything("кия")] == ["Kia Rio", "Kia Sportage"]


def test_changing_make_synonyms_rebuilds_model_index(catalog):
    """Правка синонимов в админке не должна оставлять модели со старым
    индексом — молча и без единой ошибки."""
    catalog["kia"].search_terms = "Киа, Кия, Кийка"
    catalog["kia"].save()

    assert [str(m) for m in cars.search_everything("кийка рио")] == ["Kia Rio"]


def test_search_index_survives_partial_update():
    """`update_or_create` в Django 5 сохраняет объект с
    `update_fields=set(defaults)`. Вычисленный в `save()` индекс в этот
    список не попадает сам, и без явной дописки правка синонимов молча не
    доезжала бы до базы."""
    CarMake.objects.create(name="Chery", search_terms="Чери")
    CarMake.objects.update_or_create(
        name="Chery", defaults={"search_terms": "Чери, Черри"}
    )

    assert [make.name for make in cars.search_makes("черри")] == ["Chery"]


def test_limit_is_capped(catalog):
    assert len(cars.search_makes("", limit=1000)) <= cars.MAX_LIMIT


# --------------------------------------------------------------- API


def test_makes_endpoint(api, client_user, catalog):
    api.force_authenticate(client_user)

    rows = api.get(MAKES, {"q": "мерс"}).json()

    assert [row["name"] for row in rows] == ["Mercedes-Benz"]


def test_search_endpoint_returns_ready_title(api, client_user, catalog):
    """Строку в профиль кладёт сервер: склеивать «марка + модель» на
    клиенте значит однажды склеить иначе."""
    api.force_authenticate(client_user)

    rows = api.get(SEARCH, {"q": "киа рио"}).json()

    assert rows[0]["title"] == "Kia Rio"
    assert rows[0]["make_name"] == "Kia"


def test_models_endpoint_of_a_make(api, client_user, catalog):
    api.force_authenticate(client_user)

    rows = api.get(f"{MAKES}{catalog['kia'].id}/models/").json()

    assert {row["name"] for row in rows} == {"Rio", "Sportage"}


def test_broken_limit_does_not_break_suggestions(api, client_user, catalog):
    """Подсказки обязаны работать всегда: мусор в параметре — не повод
    отдать 400 и оставить человека с пустым списком."""
    api.force_authenticate(client_user)

    response = api.get(MAKES, {"limit": "сколько-нибудь"})

    assert response.status_code == 200
    assert response.json()


def test_catalog_requires_login(api):
    assert api.get(MAKES).status_code == 401
