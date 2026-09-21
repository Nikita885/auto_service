from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import CarMake, ServicePoint
from apps.catalog.serializers import (
    CarMakeSerializer,
    CarModelSerializer,
    ServicePointSerializer,
)
from apps.catalog.services import cars as cars_service


@extend_schema(tags=["Каталог"])
class ServicePointViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Адреса сервиса. Открыты без авторизации: их видно ещё до входа."""

    serializer_class = ServicePointSerializer
    permission_classes = [AllowAny]
    pagination_class = None
    queryset = ServicePoint.objects.filter(is_active=True)


_QUERY = OpenApiParameter(
    "q",
    str,
    description="Часть названия в любом написании: «мерс», «merc», «Мерседес».",
)
_LIMIT = OpenApiParameter("limit", int, description="Сколько позиций вернуть, до 100.")


def _limit(request: Request) -> int:
    """Лимит из запроса. Мусор в параметре — не повод отдавать 400:
    подсказки должны работать всегда, а неверное число просто игнорируем."""
    try:
        return int(request.query_params.get("limit", cars_service.DEFAULT_LIMIT))
    except (TypeError, ValueError):
        return cars_service.DEFAULT_LIMIT


@extend_schema(tags=["Автомобили"])
class CarMakeListView(APIView):
    """Подсказки по маркам. Пустой запрос — список с ходовых марок."""

    @extend_schema(
        parameters=[_QUERY, _LIMIT],
        responses={200: CarMakeSerializer(many=True)},
        summary="Марки автомобилей",
    )
    def get(self, request: Request) -> Response:
        makes = cars_service.search_makes(
            request.query_params.get("q", ""), _limit(request)
        )
        return Response(CarMakeSerializer(makes, many=True).data)


@extend_schema(tags=["Автомобили"])
class CarModelListView(APIView):
    """Модели выбранной марки."""

    @extend_schema(
        parameters=[_QUERY, _LIMIT],
        responses={200: CarModelSerializer(many=True)},
        summary="Модели марки",
    )
    def get(self, request: Request, make_id) -> Response:
        make = get_object_or_404(CarMake, pk=make_id, is_active=True)
        models = cars_service.search_models(
            make, request.query_params.get("q", ""), _limit(request)
        )
        return Response(CarModelSerializer(models, many=True).data)


@extend_schema(tags=["Автомобили"])
class CarSearchView(APIView):
    """Поиск по маркам и моделям одной строкой.

    Человек набирает «киа рио» целиком, не разделяя на два поля, — и
    приложению не приходится угадывать, где кончилась марка.
    """

    @extend_schema(
        parameters=[_QUERY, _LIMIT],
        responses={200: CarModelSerializer(many=True)},
        summary="Поиск автомобиля одной строкой",
    )
    def get(self, request: Request) -> Response:
        found = cars_service.search_everything(
            request.query_params.get("q", ""), _limit(request)
        )
        return Response(CarModelSerializer(found, many=True).data)
