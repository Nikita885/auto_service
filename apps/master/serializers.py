from decimal import Decimal

from rest_framework import serializers

from apps.booking.models import Booking, BookingDraft
from apps.catalog.models import OilType


class MasterBookingSerializer(serializers.ModelSerializer):
    """Запись глазами мастера: видно клиента, машину и масло.

    Здесь телефон отдаётся полностью — мастеру нужно позвонить клиенту,
    если тот опаздывает.
    """

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    service_point_name = serializers.CharField(source="service_point.name", read_only=True)
    local_time = serializers.SerializerMethodField()
    paid_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Booking
        fields = (
            "id",
            "code",
            "status",
            "status_display",
            "service_point",
            "service_point_name",
            "start_at",
            "end_at",
            "local_time",
            "client_name",
            "client_phone",
            "car_model",
            "car_plate",
            "oil_title",
            "oil_price",
            "work_price",
            "total_price",
            "points_spent",
            "paid_amount",
            "client_comment",
            "cancel_reason",
            "created_at",
        )

    def get_local_time(self, obj: Booking) -> str:
        return obj.local_start().strftime("%d.%m.%Y %H:%M")


class MasterBookingDetailSerializer(MasterBookingSerializer):
    status_logs = serializers.SerializerMethodField()

    class Meta(MasterBookingSerializer.Meta):
        fields = MasterBookingSerializer.Meta.fields + ("status_logs",)

    def get_status_logs(self, obj: Booking) -> list[dict]:
        return [
            {
                "from_status": log.from_status,
                "to_status": log.to_status,
                "actor": log.actor.display_name if log.actor_id else None,
                "comment": log.comment,
                "created_at": log.created_at,
            }
            for log in obj.status_logs.all()
        ]


class MasterCancelSerializer(serializers.Serializer):
    """Причина обязательна: она уходит клиенту в SMS."""

    reason = serializers.CharField(max_length=500, allow_blank=False)


class MasterCompleteSerializer(serializers.Serializer):
    """Расчёт при завершении: сколько чека клиент закрывает баллами."""

    points = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal(0), required=False, default=Decimal(0),
        help_text="Баллы к списанию по желанию клиента. 0 — не списывать.",
    )


class PointsQuoteSerializer(serializers.Serializer):
    """Окно расчёта у мастера: баланс клиента и сколько можно списать."""

    balance = serializers.DecimalField(max_digits=10, decimal_places=2)
    limit = serializers.DecimalField(max_digits=10, decimal_places=2)
    max_spend = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    max_discount_percent = serializers.IntegerField()


# ------------------------------------------------------------------ масла
class OilStockRowSerializer(serializers.Serializer):
    service_point = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=0, max_value=100000)


class MasterOilSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    title = serializers.CharField(source="__str__", read_only=True)
    brand = serializers.CharField(max_length=80)
    name = serializers.CharField(max_length=120)
    viscosity = serializers.CharField(max_length=16)
    oil_type = serializers.ChoiceField(choices=OilType.choices)
    oil_type_display = serializers.CharField(source="get_oil_type_display", read_only=True)
    volume_liters = serializers.DecimalField(
        max_digits=4, decimal_places=1, min_value=Decimal("0.1")
    )
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal(0))
    work_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal(0))
    total_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_active = serializers.BooleanField(default=True)
    stock = serializers.SerializerMethodField()

    def get_stock(self, obj) -> dict:
        """Остаток по id точки. Точки без строки остатка — ноль."""
        return {str(k): v for k, v in getattr(obj, "stock_by_point", {}).items()}


class MasterOilCreateSerializer(MasterOilSerializer):
    initial_stock = OilStockRowSerializer(many=True, required=False, write_only=True)


class MasterPointShortSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MasterCatalogSerializer(serializers.Serializer):
    points = MasterPointShortSerializer(many=True)
    oils = MasterOilSerializer(many=True)


class NoShowSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class LiveDraftSerializer(serializers.ModelSerializer):
    """Кто прямо сейчас записывается. Полезно, чтобы понимать нагрузку."""

    client_name = serializers.CharField(source="user.display_name", read_only=True)
    client_phone = serializers.CharField(source="user.phone", read_only=True)
    oil_title = serializers.SerializerMethodField()
    seconds_left = serializers.IntegerField(read_only=True)

    class Meta:
        model = BookingDraft
        fields = (
            "id",
            "step",
            "client_name",
            "client_phone",
            "oil_title",
            "slot_start",
            "seconds_left",
            "created_at",
        )

    def get_oil_title(self, obj: BookingDraft) -> str | None:
        return str(obj.oil) if obj.oil_id else None


class DaySummarySerializer(serializers.Serializer):
    date = serializers.DateField()
    total = serializers.IntegerField()
    pending = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    completed = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    no_show = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    points_spent = serializers.DecimalField(max_digits=12, decimal_places=2)


# --------------------------------------------------------------- метрики
# Схема отдаётся явно, а не через `dict`: по ней генерируется OpenAPI, и
# админ-панель (как и любой будущий клиент) знает состав ответа заранее.


class MetricsPeriodSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    days = serializers.IntegerField()
    timezone = serializers.CharField()


class MetricsTotalsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    completed = serializers.IntegerField()
    pending = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    cancelled_by_client = serializers.IntegerField()
    cancelled_by_master = serializers.IntegerField()
    no_show = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    points_spent = serializers.DecimalField(max_digits=12, decimal_places=2)
    oil_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    work_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    points_spent = serializers.DecimalField(max_digits=12, decimal_places=2)
    avg_check = serializers.DecimalField(max_digits=12, decimal_places=2)
    cancel_rate = serializers.FloatField()
    no_show_rate = serializers.FloatField()
    completion_rate = serializers.FloatField()


class FunnelStepSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()
    share = serializers.FloatField()


class MetricsFunnelSerializer(serializers.Serializer):
    started = serializers.IntegerField()
    point_selected = serializers.IntegerField()
    oil_selected = serializers.IntegerField()
    slot_selected = serializers.IntegerField()
    confirmed = serializers.IntegerField()
    expired = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    restarted = serializers.IntegerField()
    alive = serializers.IntegerField()
    conversion = serializers.FloatField()
    steps = FunnelStepSerializer(many=True)


class MetricsDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    total = serializers.IntegerField()
    completed = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=12, decimal_places=2)


class MetricsHourSerializer(serializers.Serializer):
    hour = serializers.IntegerField()
    total = serializers.IntegerField()


class MetricsPointSerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    total = serializers.IntegerField()
    completed = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=12, decimal_places=2)


class MetricsOilSerializer(serializers.Serializer):
    oil_title = serializers.CharField()
    total = serializers.IntegerField()
    completed = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=12, decimal_places=2)


class MetricsClientsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    new = serializers.IntegerField()
    returning = serializers.IntegerField()


class MetricsStockItemSerializer(serializers.Serializer):
    point = serializers.CharField()
    oil = serializers.CharField()
    quantity = serializers.IntegerField()
    is_low = serializers.BooleanField()


class MetricsStockSerializer(serializers.Serializer):
    threshold = serializers.IntegerField()
    total_quantity = serializers.IntegerField()
    low_count = serializers.IntegerField()
    items = MetricsStockItemSerializer(many=True)


class MetricsLiveSerializer(serializers.Serializer):
    drafts_now = serializers.IntegerField()
    upcoming = serializers.IntegerField()


class MetricsSerializer(serializers.Serializer):
    period = MetricsPeriodSerializer()
    totals = MetricsTotalsSerializer()
    funnel = MetricsFunnelSerializer()
    by_day = MetricsDaySerializer(many=True)
    by_hour = MetricsHourSerializer(many=True)
    by_point = MetricsPointSerializer(many=True)
    top_oils = MetricsOilSerializer(many=True)
    clients = MetricsClientsSerializer()
    stock = MetricsStockSerializer()
    live = MetricsLiveSerializer()
