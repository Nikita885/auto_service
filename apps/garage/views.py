"""API гаража: автомобили клиента.

Только роль `client`: машины сотрудника записи не касаются, а чужие машины
сервис отдаёт как «не найдено» — по ответу не понять, существует ли id.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.permissions import IsClient
from apps.garage.serializers import (
    CarSerializer,
    CarWriteSerializer,
    EntrySerializer,
    EntryWriteSerializer,
    SummarySerializer,
)
from apps.garage.services import cars as cars_service
from apps.garage.services import journal as journal_service


def _write_data(request: Request, *, partial: bool) -> tuple[dict, bool]:
    payload = CarWriteSerializer(data=request.data, partial=partial)
    payload.is_valid(raise_exception=True)
    data = dict(payload.validated_data)
    return data, bool(data.pop("is_primary", False))


@extend_schema(tags=["Гараж"])
class CarViewSet(viewsets.ViewSet):
    permission_classes = [IsClient]
    # id в адресе — UUID: так его видит схема OpenAPI, а мусор вместо id
    # отсекается маршрутом, не доходя до базы.
    lookup_value_converter = "uuid"

    @extend_schema(responses={200: CarSerializer(many=True)}, summary="Мои автомобили")
    def list(self, request: Request) -> Response:
        cars = cars_service.list_cars(request.user)
        return Response(CarSerializer(cars, many=True).data)

    @extend_schema(
        request=CarWriteSerializer, responses={201: CarSerializer},
        summary="Добавить автомобиль",
        description="Первый автомобиль сразу становится основным.",
    )
    def create(self, request: Request) -> Response:
        data, primary = _write_data(request, partial=False)
        car = cars_service.create_car(request.user, make_primary=primary, **data)
        return Response(CarSerializer(car).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: CarSerializer}, summary="Автомобиль")
    def retrieve(self, request: Request, pk=None) -> Response:
        return Response(CarSerializer(cars_service.get_car(request.user, pk)).data)

    @extend_schema(
        request=CarWriteSerializer, responses={200: CarSerializer},
        summary="Изменить автомобиль",
    )
    def partial_update(self, request: Request, pk=None) -> Response:
        data, primary = _write_data(request, partial=True)
        car = cars_service.update_car(request.user, pk, make_primary=primary, **data)
        return Response(CarSerializer(car).data)

    @extend_schema(
        responses={204: None}, summary="Удалить автомобиль",
        description="Записи с этой машиной остаются в истории как были.",
    )
    def destroy(self, request: Request, pk=None) -> Response:
        cars_service.archive_car(request.user, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={200: CarSerializer}, summary="Сделать основным")
    @action(detail=True, methods=["post"], url_path="make-primary")
    def make_primary(self, request: Request, pk=None) -> Response:
        return Response(CarSerializer(cars_service.set_primary(request.user, pk)).data)

    @extend_schema(
        responses={200: SummarySerializer}, summary="Гараж: сводка по машине",
        description=(
            "Пробег, напоминания (масло, ОСАГО, техосмотр, резина), расходы за "
            "месяц и год по категориям, расход топлива и последние записи — "
            "одним ответом для главного экрана гаража."
        ),
    )
    @action(detail=True, methods=["get"])
    def summary(self, request: Request, pk=None) -> Response:
        return Response(SummarySerializer(journal_service.summary(request.user, pk)).data)

    @extend_schema(
        methods=["get"],
        parameters=[OpenApiParameter("limit", int, description="Сколько строк, по умолчанию 50")],
        responses={200: EntrySerializer(many=True)}, summary="Дневник машины",
    )
    @extend_schema(
        methods=["post"], request=EntryWriteSerializer, responses={201: EntrySerializer},
        summary="Добавить запись в дневник",
        description="Пробег машины поднимается до наибольшего известного.",
    )
    @action(detail=True, methods=["get", "post"])
    def journal(self, request: Request, pk=None) -> Response:
        if request.method == "POST":
            payload = EntryWriteSerializer(data=request.data)
            payload.is_valid(raise_exception=True)
            entry = journal_service.add_entry(request.user, pk, **payload.validated_data)
            return Response(EntrySerializer(_item(entry)).data, status=status.HTTP_201_CREATED)
        try:
            limit = int(request.query_params.get("limit", 50))
        except ValueError:
            limit = 50
        rows = journal_service.journal(request.user, pk, limit=limit)
        return Response(EntrySerializer(rows, many=True).data)


def _item(entry) -> journal_service.Item:
    return journal_service.Item(
        id=str(entry.pk), kind=entry.kind, date=entry.date, mileage=entry.mileage,
        amount=entry.amount, liters=entry.liters, full_tank=entry.full_tank,
        note=entry.note, source="manual",
    )


@extend_schema(tags=["Гараж"])
class EntryViewSet(viewsets.ViewSet):
    """Своя запись дневника: поправить или удалить. Замены у нас — только читать."""

    permission_classes = [IsClient]
    lookup_value_converter = "uuid"

    @extend_schema(request=EntryWriteSerializer, responses={200: EntrySerializer},
                   summary="Изменить запись дневника")
    def partial_update(self, request: Request, pk=None) -> Response:
        payload = EntryWriteSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        entry = journal_service.update_entry(request.user, pk, **payload.validated_data)
        return Response(EntrySerializer(_item(entry)).data)

    @extend_schema(responses={204: None}, summary="Удалить запись дневника")
    def destroy(self, request: Request, pk=None) -> Response:
        journal_service.delete_entry(request.user, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
