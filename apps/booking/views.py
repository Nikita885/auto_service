"""API клиента: доступность, черновик записи, свои записи.

Вьюхи максимально тонкие: разобрать вход сериализатором, вызвать сервис,
отдать результат. Ни одного `if` по бизнес-правилам здесь быть не должно.
"""

from __future__ import annotations

from datetime import datetime

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.booking.constants import ACTIVE_BOOKING_STATUSES
from apps.booking.models import Booking, BookingDraft
from apps.booking.serializers import (
    BookingDetailSerializer,
    BookingDraftSerializer,
    BookingSerializer,
    CancelSerializer,
    ConfirmDraftSerializer,
    SelectOilSerializer,
    SelectPointSerializer,
    SelectSlotSerializer,
    StartDraftSerializer,
)
from apps.booking.services import booking as booking_service
from apps.booking.services import draft as draft_service
from apps.booking.services import slots as slots_service
from apps.booking.services import stock as stock_service
from apps.catalog.models import ServicePoint
from apps.catalog.serializers import AvailableOilSerializer, SlotSerializer
from apps.common.exceptions import ValidationError


def _active_point(point_id) -> ServicePoint:
    return get_object_or_404(ServicePoint, pk=point_id, is_active=True)


@extend_schema(tags=["Доступность"])
class PointOilsView(APIView):
    """Масла, доступные на точке прямо сейчас.

    Живёт в booking, а не в catalog, потому что доступность зависит от
    броней и черновиков — это область записи, а не справочника.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: AvailableOilSerializer(many=True)},
        summary="Масла в наличии на точке",
    )
    def get(self, request: Request, point_id) -> Response:
        point = _active_point(point_id)
        draft = draft_service.get_open_draft(request.user)

        oils = stock_service.available_oils(
            point, exclude_draft_id=draft.pk if draft else None
        )
        return Response(AvailableOilSerializer(oils, many=True).data)


@extend_schema(tags=["Доступность"])
class PointSlotsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "date",
                str,
                description="YYYY-MM-DD. Без параметра вернётся список дат, "
                "где есть свободное время.",
            )
        ],
        responses={200: SlotSerializer(many=True)},
        summary="Свободное время на точке",
    )
    def get(self, request: Request, point_id) -> Response:
        point = _active_point(point_id)
        draft = draft_service.get_open_draft(request.user)
        exclude = draft.pk if draft else None

        raw_date = request.query_params.get("date")
        if not raw_date:
            days = slots_service.available_days(point)
            return Response({"available_days": [d.isoformat() for d in days]})

        try:
            day = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError(
                "Дата должна быть в формате YYYY-MM-DD", code="bad_date"
            ) from exc

        slots = slots_service.build_slots(point, day, exclude_draft_id=exclude)
        return Response(
            {
                "date": day.isoformat(),
                "slots": SlotSerializer(slots, many=True).data,
            }
        )


@extend_schema(tags=["Запись: черновик"])
class BookingDraftViewSet(
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Пошаговая запись.

    Черновик создаётся при первом обращении и живёт 5 минут. Каждый шаг
    возвращает полное состояние — клиенту не нужно склеивать ответы.
    """

    serializer_class = BookingDraftSerializer
    permission_classes = [IsAuthenticated]
    throttle_scope = "booking_write"
    lookup_url_kwarg = "pk"

    queryset = BookingDraft.objects.none()  # для генерации схемы

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset
        return BookingDraft.objects.filter(user=self.request.user).select_related(
            "service_point", "oil", "booking"
        )

    @extend_schema(
        request=StartDraftSerializer,
        responses={201: BookingDraftSerializer},
        summary="Начать запись (создать черновик)",
        description=(
            "Возвращает существующий живой черновик, если он есть. "
            "`restart: true` — принудительно начать заново."
        ),
    )
    def create(self, request: Request) -> Response:
        payload = StartDraftSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        draft = draft_service.start_draft(
            request.user, restart=payload.validated_data["restart"]
        )
        return Response(
            BookingDraftSerializer(draft).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        responses={200: BookingDraftSerializer},
        summary="Текущий черновик",
        description="204, если активной попытки записи нет.",
    )
    @action(detail=False, methods=["get"])
    def current(self, request: Request) -> Response:
        draft = draft_service.get_open_draft(request.user)
        if draft is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(BookingDraftSerializer(draft).data)

    @extend_schema(
        request=SelectPointSerializer,
        responses={200: BookingDraftSerializer},
        summary="Шаг 1: выбрать адрес",
    )
    @action(detail=True, methods=["post"], url_path="select-point")
    def select_point(self, request: Request, pk=None) -> Response:
        payload = SelectPointSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        draft = draft_service.select_point(
            request.user, pk, payload.validated_data["service_point_id"]
        )
        return Response(BookingDraftSerializer(draft).data)

    @extend_schema(
        request=SelectOilSerializer,
        responses={200: BookingDraftSerializer},
        summary="Шаг 2: выбрать масло",
    )
    @action(detail=True, methods=["post"], url_path="select-oil")
    def select_oil(self, request: Request, pk=None) -> Response:
        payload = SelectOilSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        draft = draft_service.select_oil(
            request.user, pk, payload.validated_data["oil_id"]
        )
        return Response(BookingDraftSerializer(draft).data)

    @extend_schema(
        request=SelectSlotSerializer,
        responses={200: BookingDraftSerializer},
        summary="Шаг 3: выбрать время",
    )
    @action(detail=True, methods=["post"], url_path="select-slot")
    def select_slot(self, request: Request, pk=None) -> Response:
        payload = SelectSlotSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        draft = draft_service.select_slot(
            request.user, pk, payload.validated_data["start_at"]
        )
        return Response(BookingDraftSerializer(draft).data)

    @extend_schema(
        request=ConfirmDraftSerializer,
        responses={201: BookingSerializer},
        summary="Шаг 4: подтвердить запись",
        description=(
            "Слот и наличие масла проверяются повторно. Если за время "
            "заполнения слот заняли — 409 `slot_taken`."
        ),
    )
    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, pk=None) -> Response:
        payload = ConfirmDraftSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        booking = draft_service.confirm(
            request.user, pk, comment=payload.validated_data.get("comment", "")
        )
        return Response(
            BookingSerializer(booking).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        responses={200: BookingDraftSerializer},
        summary="Прервать запись",
        description="Освобождает удерживаемый слот и канистру сразу, не дожидаясь таймера.",
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk=None) -> Response:
        draft = draft_service.cancel_draft(request.user, pk)
        return Response(BookingDraftSerializer(draft).data)


@extend_schema(tags=["Запись: мои записи"])
class BookingViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsAuthenticated]

    queryset = Booking.objects.none()  # для генерации схемы

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset
        qs = (
            Booking.objects.for_user(self.request.user)
            .select_related("service_point", "oil")
            .order_by("-start_at")
        )
        if self.action == "retrieve":
            qs = qs.prefetch_related("status_logs__actor")

        scope = self.request.query_params.get("scope")
        if scope == "upcoming":
            qs = qs.active().filter(start_at__gte=timezone.now()).order_by("start_at")
        elif scope == "history":
            # Всё, что не «предстоящее»: завершённые, отменённые и просроченные.
            qs = qs.exclude(
                status__in=ACTIVE_BOOKING_STATUSES, start_at__gte=timezone.now()
            )
        return qs

    def get_serializer_class(self):
        return BookingDetailSerializer if self.action == "retrieve" else BookingSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "scope", str, description="upcoming | history. По умолчанию — все."
            )
        ],
        summary="Мои записи",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=CancelSerializer,
        responses={200: BookingSerializer},
        summary="Отменить свою запись",
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk=None) -> Response:
        payload = CancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        booking = booking_service.cancel_by_client(
            request.user, pk, reason=payload.validated_data.get("reason", "")
        )
        return Response(BookingSerializer(booking).data)
