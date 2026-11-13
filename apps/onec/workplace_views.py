from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsMaster
from apps.onec.services import workplace
from apps.onec.workplace_serializers import (
    CheckoutEventSerializer,
    CheckoutPrepareSerializer,
    OrderSaveSerializer,
    PointsQuoteSerializer,
)


class WorkplaceView(APIView):
    """Обычный JWT сотрудника, без отдельного фонового ключа обмена."""

    permission_classes = [IsMaster]


@extend_schema(tags=["Рабочее место 1С"])
class WorkplaceQuoteView(WorkplaceView):
    @extend_schema(parameters=[PointsQuoteSerializer], responses={200: dict})
    def get(self, request, booking_id):
        payload = PointsQuoteSerializer(data=request.query_params)
        payload.is_valid(raise_exception=True)
        return Response(workplace.quote(request.user, booking_id, **payload.validated_data))


@extend_schema(tags=["Рабочее место 1С"])
class WorkplaceOrderView(WorkplaceView):
    @extend_schema(responses={200: dict}, summary="Состав обслуживания и состояние расчёта")
    def get(self, request, booking_id):
        return Response({"order": workplace.get(request.user, booking_id)})

    @extend_schema(
        request=OrderSaveSerializer, responses={200: dict}, summary="Сохранить состав обслуживания"
    )
    def post(self, request, booking_id):
        payload = OrderSaveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return Response(
            {"order": workplace.save(request.user, booking_id, **payload.validated_data)}
        )


@extend_schema(tags=["Рабочее место 1С"])
class WorkplacePrepareView(WorkplaceView):
    @extend_schema(
        request=CheckoutPrepareSerializer,
        responses={200: dict},
        summary="Зафиксировать расчёт и зарезервировать баллы",
    )
    def post(self, request, booking_id):
        payload = CheckoutPrepareSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return Response(
            {"order": workplace.prepare(request.user, booking_id, **payload.validated_data)}
        )


@extend_schema(tags=["Рабочее место 1С"])
class WorkplaceEventView(WorkplaceView):
    @extend_schema(
        request=CheckoutEventSerializer,
        responses={200: dict},
        summary="Зафиксировать результат оборудования",
    )
    def post(self, request, booking_id):
        payload = CheckoutEventSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return Response(
            {"order": workplace.advance(request.user, booking_id, **payload.validated_data)}
        )
