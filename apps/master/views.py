"""API для приложения мастера (вторая версия клиента).

Отдельное приложение, а не флаг в клиентском API: у мастера другой набор
полей (видит телефон и машину чужого человека) и другие права. Смешивать
их в одном сериализаторе — верный способ однажды отдать клиенту чужие
персональные данные.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count, F, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.booking.constants import BookingStatus
from apps.booking.models import Booking, BookingDraft
from apps.booking.services import booking as booking_service
from apps.catalog.models import ServicePoint
from apps.catalog.services import oils as oils_service
from apps.common.exceptions import NotFoundError, ValidationError
from apps.common.permissions import IsAdmin, IsMaster
from apps.master import metrics
from apps.master.serializers import (
    DaySummarySerializer,
    LiveDraftSerializer,
    MasterBookingDetailSerializer,
    MasterBookingSerializer,
    MasterCancelSerializer,
    MasterCatalogSerializer,
    MasterCompleteSerializer,
    MasterOilCreateSerializer,
    MasterOilSerializer,
    MetricsSerializer,
    NoShowSerializer,
    OilStockRowSerializer,
    PointsQuoteSerializer,
)
from apps.referral.services import points as referral_points


def _parse_date(raw: str):
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(
            "Дата должна быть в формате YYYY-MM-DD", code="bad_date"
        ) from exc


def _resolve_tz(request) -> zoneinfo.ZoneInfo:
    """Часовой пояс, в котором считаем «сутки».

    Если запрос про конкретную точку — берём её пояс. Иначе общий
    рабочий пояс сети: для двух адресов в одном городе это одно и то же,
    но при выходе в другой регион правило останется корректным.
    """
    point_id = request.query_params.get("service_point")
    if point_id:
        point = ServicePoint.objects.filter(pk=point_id).only("timezone").first()
        if point is not None:
            return point.tz
    return zoneinfo.ZoneInfo(settings.BUSINESS_TIMEZONE)


def _day_bounds(day, tz):
    """Границы локальных суток в UTC."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    return start, start + timedelta(days=1)


@extend_schema(tags=["Мастер"])
class MasterBookingViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    permission_classes = [IsMaster]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return MasterBookingDetailSerializer
        return MasterBookingSerializer

    queryset = Booking.objects.none()  # для генерации схемы

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset
        qs = Booking.objects.select_related("service_point", "oil", "user")

        # Мастер видит только свои точки; у админа ограничения нет.
        allowed = self.request.user.accessible_point_ids()
        if allowed is not None:
            qs = qs.filter(service_point_id__in=allowed)

        params = self.request.query_params

        if point_id := params.get("service_point"):
            qs = qs.filter(service_point_id=point_id)

        if status_filter := params.get("status"):
            qs = qs.filter(status__in=status_filter.split(","))

        if raw_date := params.get("date"):
            since, until = _day_bounds(_parse_date(raw_date), _resolve_tz(self.request))
            qs = qs.filter(start_at__gte=since, start_at__lt=until)

        if params.get("scope") == "today":
            now = timezone.now()
            qs = qs.filter(
                start_at__gte=now - timedelta(hours=12),
                start_at__lte=now + timedelta(hours=36),
            )

        if search := params.get("search"):
            qs = qs.filter(
                Q(code__icontains=search)
                | Q(client_name__icontains=search)
                | Q(client_phone__icontains=search)
                | Q(car_plate__icontains=search)
            )

        if self.action == "retrieve":
            qs = qs.prefetch_related("status_logs__actor")

        return qs.order_by("start_at")

    @extend_schema(
        parameters=[
            OpenApiParameter("date", str, description="YYYY-MM-DD — записи за день"),
            OpenApiParameter("status", str, description="Через запятую: pending,in_progress"),
            OpenApiParameter("service_point", str, description="UUID точки"),
            OpenApiParameter("search", str, description="Код, имя, телефон или госномер"),
            OpenApiParameter("scope", str, description="today — ближайшие сутки"),
        ],
        summary="Список записей",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=MasterCancelSerializer,
        responses={200: MasterBookingSerializer},
        summary="Отменить запись",
        description=(
            "Причина обязательна — она уходит клиенту в SMS. "
            "Уведомление отправляется автоматически."
        ),
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk=None) -> Response:
        payload = MasterCancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        booking = booking_service.cancel_by_master(
            request.user, pk, reason=payload.validated_data["reason"]
        )
        return Response(MasterBookingSerializer(booking).data)

    @extend_schema(responses={200: MasterBookingSerializer}, summary="Взять в работу")
    @action(detail=True, methods=["post"])
    def start(self, request: Request, pk=None) -> Response:
        booking = booking_service.start_work(request.user, pk)
        return Response(MasterBookingSerializer(booking).data)

    @extend_schema(
        request=MasterCompleteSerializer,
        responses={200: MasterBookingSerializer},
        summary="Работы выполнены",
        description=(
            "Расчёт одной транзакцией: списание баллов по желанию клиента "
            "(не больше потолка от чека), списание канистры со склада и "
            "баллы в плечи вышестоящих клиента."
        ),
    )
    @action(detail=True, methods=["post"])
    def complete(self, request: Request, pk=None) -> Response:
        payload = MasterCompleteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        booking = booking_service.complete(
            request.user, pk, points=payload.validated_data["points"]
        )
        return Response(MasterBookingSerializer(booking).data)

    @extend_schema(
        responses={200: PointsQuoteSerializer},
        summary="Баллы клиента для расчёта",
        description="Баланс клиента и сколько из него можно списать в этот чек.",
    )
    @action(detail=True, methods=["get"])
    def points(self, request: Request, pk=None) -> Response:
        booking = booking_service.get_for_master(request.user, pk)
        return Response(PointsQuoteSerializer(referral_points.spend_quote(booking)).data)

    @extend_schema(
        request=NoShowSerializer,
        responses={200: MasterBookingSerializer},
        summary="Клиент не приехал",
    )
    @action(detail=True, methods=["post"], url_path="no-show")
    def no_show(self, request: Request, pk=None) -> Response:
        payload = NoShowSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        booking = booking_service.mark_no_show(
            request.user, pk, reason=payload.validated_data.get("reason", "")
        )
        return Response(MasterBookingSerializer(booking).data)

    @extend_schema(
        parameters=[OpenApiParameter("date", str, description="YYYY-MM-DD")],
        responses={200: DaySummarySerializer},
        summary="Сводка за день",
    )
    @action(detail=False, methods=["get"])
    def summary(self, request: Request) -> Response:
        raw_date = request.query_params.get("date")
        tz = _resolve_tz(request)
        day = _parse_date(raw_date) if raw_date else timezone.now().astimezone(tz).date()

        since, until = _day_bounds(day, tz)
        qs = Booking.objects.filter(start_at__gte=since, start_at__lt=until)

        allowed = request.user.accessible_point_ids()
        if allowed is not None:
            qs = qs.filter(service_point_id__in=allowed)
        if point_id := request.query_params.get("service_point"):
            qs = qs.filter(service_point_id=point_id)

        stats = qs.aggregate(
            total=Count("id"),
            pending=Count("id", filter=Q(status=BookingStatus.PENDING)),
            in_progress=Count("id", filter=Q(status=BookingStatus.IN_PROGRESS)),
            completed=Count("id", filter=Q(status=BookingStatus.COMPLETED)),
            cancelled=Count(
                "id",
                filter=Q(
                    status__in=[
                        BookingStatus.CANCELLED_BY_CLIENT,
                        BookingStatus.CANCELLED_BY_MASTER,
                    ]
                ),
            ),
            no_show=Count("id", filter=Q(status=BookingStatus.NO_SHOW)),
            # Выручка — деньгами: часть чека, закрытая баллами, в кассу не пришла.
            revenue=Sum(
                F("total_price") - F("points_spent"),
                filter=Q(status=BookingStatus.COMPLETED),
            ),
            points_spent=Sum("points_spent", filter=Q(status=BookingStatus.COMPLETED)),
        )
        stats["date"] = day
        stats["revenue"] = stats["revenue"] or 0
        stats["points_spent"] = stats["points_spent"] or 0
        return Response(DaySummarySerializer(stats).data)


@extend_schema(tags=["Мастер"])
class LiveDraftListView(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Клиенты, которые записываются прямо сейчас.

    Не обязательный экран, но полезный: видно, что через минуту приедет
    ещё одна заявка, и на какое масло.
    """

    permission_classes = [IsMaster]
    serializer_class = LiveDraftSerializer
    pagination_class = None

    queryset = BookingDraft.objects.none()  # для генерации схемы

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset
        qs = BookingDraft.objects.alive().select_related("user", "oil", "service_point")
        allowed = self.request.user.accessible_point_ids()
        if allowed is not None:
            qs = qs.filter(service_point_id__in=allowed)
        return qs.order_by("created_at")


@extend_schema(tags=["Мастер"])
class MetricsView(APIView):
    """Сводная аналитика сети. Только для роли `admin`.

    Вьюха тонкая: разбирает фильтры, зовёт `metrics.collect` и отдаёт
    результат. Все вычисления живут в `apps/master/metrics.py`.
    """

    permission_classes = [IsAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter("date_from", str, description="YYYY-MM-DD, начало периода"),
            OpenApiParameter("date_to", str, description="YYYY-MM-DD, конец периода"),
            OpenApiParameter("service_point", str, description="UUID точки — фильтр"),
        ],
        responses={200: MetricsSerializer},
        summary="Метрики за период",
        description=(
            "Сводная аналитика по сети: выручка и средний чек, статусы записей, "
            "воронка записи, динамика по дням, загрузка по часам, сравнение точек, "
            "популярные позиции масла, остатки склада и клиентская база. "
            "По умолчанию — последние 30 дней в часовом поясе сети; при фильтре по "
            "точке сутки считаются в её поясе. Доступно только роли `admin`."
        ),
    )
    def get(self, request: Request) -> Response:
        point = None
        if point_id := request.query_params.get("service_point"):
            point = ServicePoint.objects.filter(pk=point_id).first()
            if point is None:
                raise NotFoundError("Точка не найдена", code="point_not_found")

        period = metrics.resolve_period(
            request.query_params.get("date_from"),
            request.query_params.get("date_to"),
            point,
        )
        return Response(MetricsSerializer(metrics.collect(period, point)).data)


@extend_schema(tags=["Мастер"])
class MasterOilViewSet(viewsets.ViewSet):
    """Масла и остатки: мастер заводит новое масло и пересчитывает полку.

    Каталог общий на сеть, остатки — только по своим точкам.
    """

    permission_classes = [IsMaster]

    @extend_schema(responses={200: MasterCatalogSerializer}, summary="Масла и остатки")
    def list(self, request: Request) -> Response:
        points, oils = oils_service.catalog_for(request.user)
        return Response(MasterCatalogSerializer({"points": points, "oils": oils}).data)

    @extend_schema(
        request=MasterOilCreateSerializer,
        responses={201: MasterOilSerializer},
        summary="Новое масло",
        description="Сразу можно задать остатки на своих точках (`initial_stock`).",
    )
    def create(self, request: Request) -> Response:
        payload = MasterOilCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        stock = {row["service_point"]: row["quantity"] for row in data.pop("initial_stock", [])}
        oil = oils_service.create_oil(request.user, stock=stock, **data)
        _, oils = oils_service.catalog_for(request.user)
        oil = next(item for item in oils if item.pk == oil.pk)
        return Response(MasterOilSerializer(oil).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=MasterOilSerializer,
        responses={200: MasterOilSerializer},
        summary="Изменить масло",
        description="Цена, стоимость работ, «в продаже» и т. п. Уже созданные записи "
        "не меняются — в них снимок цены.",
    )
    def partial_update(self, request: Request, pk=None) -> Response:
        payload = MasterOilSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        oils_service.update_oil(request.user, pk, **payload.validated_data)
        _, oils = oils_service.catalog_for(request.user)
        oil = next(item for item in oils if str(item.pk) == str(pk))
        return Response(MasterOilSerializer(oil).data)

    @extend_schema(
        request=OilStockRowSerializer,
        responses={200: OilStockRowSerializer},
        summary="Остаток на точке",
        description="Абсолютное число канистр после пересчёта или прихода.",
    )
    @action(detail=True, methods=["post"])
    def stock(self, request: Request, pk=None) -> Response:
        payload = OilStockRowSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        row = oils_service.set_stock(
            request.user, pk, payload.validated_data["service_point"],
            payload.validated_data["quantity"],
        )
        return Response({"service_point": str(row.service_point_id), "quantity": row.quantity})
