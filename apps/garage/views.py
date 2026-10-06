"""API гаража: автомобили клиента.

Только роль `client`: машины сотрудника записи не касаются, а чужие машины
сервис отдаёт как «не найдено» — по ответу не понять, существует ли id.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.permissions import IsClient
from apps.garage.serializers import CarSerializer, CarWriteSerializer
from apps.garage.services import cars as cars_service


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
