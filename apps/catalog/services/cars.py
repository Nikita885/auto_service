"""Подсказки по маркам и моделям автомобилей.

Поиск построен на предпосчитанной поисковой форме (`search_index`): и
запрос, и справочник приводятся к латинице без разделителей, после чего
хватает обычных `startswith`/`contains`. Это находит «мерс», «merc»,
«Мерседес» и «MERCEDES-BENZ» одним и тем же запросом, не требуя ни
полнотекстового индекса PostgreSQL, ни расширения pg_trgm — а значит не
привязывает проект к конкретной сборке базы.

Два правила, каждое из которых появилось после проверки на живых данных:

1. **Совпадение только с начала слова.** Простой `contains` по «рио»
   выдавал UAZ: внутри «patriot» есть «rio». Человек набирает начало
   слова, а не его середину.
2. **Слова запроса ищутся по отдельности и все сразу.** «киа рио» после
   нормализации склеивалось в «kiario» и не находило ничего. Теперь
   каждое слово должно найтись в индексе — порядок значения не имеет,
   поэтому работает и «рио киа».

Чего поиск не умеет: прощать опечатки и склонения. «мерсдес» и «весту» не
найдутся, «вест» — найдётся. Лечится триграммами в PostgreSQL, но браться
за это стоит, когда станет видно, что люди действительно промахиваются.
"""

from __future__ import annotations

from django.db.models import Case, IntegerField, Q, QuerySet, Value, When

from apps.catalog.models import CarMake, CarModel
from apps.common.translit import normalize

# Сколько позиций отдаём в подсказку. Больше двадцати в выпадающем списке
# на телефоне всё равно не читают, а запрос из одной буквы иначе тянул бы
# весь справочник.
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def tokens(query: str) -> list[str]:
    """Слова запроса в поисковой форме. Пустые отбрасываем."""
    return [token for word in query.split() if (token := normalize(word))]


def _word_start(token: str) -> Q:
    """Совпадение с началом любого слова в индексе.

    Части индекса склеены через пробел, поэтому «начало слова» — это либо
    начало всей строки, либо позиция сразу после пробела.
    """
    return Q(search_index__startswith=token) | Q(search_index__contains=f" {token}")


def _matching(queryset: QuerySet, parts: list[str]) -> QuerySet:
    for token in parts:
        queryset = queryset.filter(_word_start(token))
    return queryset


def _ranked(queryset: QuerySet, first: str, *ordering: str) -> QuerySet:
    """Сначала то, где с запроса начинается само название.

    Индекс начинается с канонического имени, поэтому `startswith` — это
    «совпало с маркой», а не «совпало с каким-то из синонимов».
    """
    return queryset.annotate(
        match_rank=Case(
            When(search_index__startswith=first, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by("match_rank", *ordering)


def search_makes(query: str = "", limit: int = DEFAULT_LIMIT) -> QuerySet:
    """Марки. Пустой запрос — список с ходовых, в порядке из справочника."""
    makes = CarMake.objects.filter(is_active=True)
    parts = tokens(query)
    if parts:
        makes = _ranked(_matching(makes, parts), parts[0], "sort_order", "name")
    return makes[: _clamp(limit)]


def search_models(
    make: CarMake, query: str = "", limit: int = DEFAULT_LIMIT
) -> QuerySet:
    """Модели выбранной марки."""
    models = CarModel.objects.filter(make=make, is_active=True)
    parts = tokens(query)
    if parts:
        models = _ranked(_matching(models, parts), parts[0], "name")
    return models[: _clamp(limit)]


def search_everything(query: str, limit: int = DEFAULT_LIMIT) -> QuerySet:
    """Поиск по моделям всех марок сразу.

    Нужен для строки «Kia Rio» целиком: человек набирает марку и модель
    подряд, не задумываясь, что это два справочника. Имя марки и её
    синонимы входят в индекс модели как раз ради этого случая.
    """
    parts = tokens(query)
    if not parts:
        return CarModel.objects.none()

    found = _matching(
        CarModel.objects.filter(is_active=True, make__is_active=True), parts
    ).select_related("make")
    return _ranked(found, parts[0], "make__sort_order", "make__name", "name")[
        : _clamp(limit)
    ]


def _clamp(limit: int) -> int:
    return max(1, min(limit or DEFAULT_LIMIT, MAX_LIMIT))
