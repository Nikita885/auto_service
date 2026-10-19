from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.booking.constants import CallOutcome, CallReason
from apps.booking.models import Booking, BookingCall, BookingDraft
from apps.catalog.models import OilType, ServiceJournalKind
from apps.catalog.serializers import AvailableOilSerializer
from apps.garage.serializers import CarShortSerializer


class BookingItemSerializer(serializers.Serializer):
    """Позиция чека глазами мастера — с ценой: из неё и считается чек."""

    id = serializers.UUIDField(read_only=True)
    service = serializers.UUIDField(source="service_id", read_only=True)
    title = serializers.CharField(read_only=True)
    category_title = serializers.CharField(read_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    material_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True
    )
    quantity = serializers.IntegerField(read_only=True)


class MasterBookingSerializer(serializers.ModelSerializer):
    """Запись глазами мастера: видно клиента, машину и масло.

    Здесь телефон отдаётся полностью — мастеру нужно позвонить клиенту,
    если тот опаздывает.
    """

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    service_point_name = serializers.CharField(source="service_point.name", read_only=True)
    local_time = serializers.SerializerMethodField()
    paid_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(
        source="charged_price", max_digits=10, decimal_places=2, read_only=True,
        help_text="Итог к оплате: правка мастера при расчёте или цена брони",
    )
    needs_service = serializers.SerializerMethodField(
        help_text="Клиент просил подобрать услугу на месте: перезвонить и выбрать (set-service)"
    )
    needs_oil = serializers.SerializerMethodField(
        help_text="То же, что needs_service. Устарело: останется, пока обновляются панели"
    )
    services = serializers.SerializerMethodField(
        help_text="Позиции чека: услуга, цена, материал, количество"
    )

    class Meta:
        model = Booking
        fields = (
            "id",
            "code",
            "status",
            "status_display",
            "needs_service",
            "needs_oil",
            "service_point",
            "service_point_name",
            "start_at",
            "end_at",
            "local_time",
            "client_name",
            "client_phone",
            "car_model",
            "car_plate",
            "service_category",
            "category_title",
            "service_title",
            "services",
            # Прежние поля масла: в них тот же снимок, пока не удалены.
            "oil_title",
            "oil_price",
            "material_price",
            "work_price",
            "total_price",
            "final_price",
            "points_spent",
            "paid_amount",
            "client_comment",
            "cancel_reason",
            "created_at",
        )

    def get_local_time(self, obj: Booking) -> str:
        return obj.local_start().strftime("%d.%m.%Y %H:%M")

    def get_needs_service(self, obj: Booking) -> bool:
        """Услуги в записи нет: мастер перезванивает и выбирает её."""
        return not obj.items.all()

    def get_needs_oil(self, obj: Booking) -> bool:
        return self.get_needs_service(obj)

    @extend_schema_field(BookingItemSerializer(many=True))
    def get_services(self, obj: Booking):
        return BookingItemSerializer(obj.items.all(), many=True).data


class MasterBookingDetailSerializer(MasterBookingSerializer):
    status_logs = serializers.SerializerMethodField()
    price_changes = serializers.SerializerMethodField()

    class Meta(MasterBookingSerializer.Meta):
        fields = MasterBookingSerializer.Meta.fields + ("status_logs", "price_changes")

    def get_price_changes(self, obj: Booking) -> list[dict]:
        """Кто, когда и почему менял итог при расчёте."""
        return [
            {
                "old_price": str(change.old_price),
                "new_price": str(change.new_price),
                "reason": change.reason,
                "actor": change.actor.display_name if change.actor_id else None,
                "created_at": change.created_at,
            }
            for change in obj.price_changes.all()
        ]

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
    """Расчёт при завершении: итог к оплате и сколько из него закрыть баллами."""

    points = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal(0), required=False, default=Decimal(0),
        help_text="Баллы к списанию по желанию клиента. 0 — не списывать.",
    )
    final_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=False,
        allow_null=True, default=None,
        help_text="Итог, если он отличается от цены брони: долили масла, добавили "
        "работу, уступили. Не передан — платят цену брони.",
    )
    reason = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default="",
        help_text="Почему изменён итог. Необязательно.",
    )
    service = serializers.UUIDField(
        required=False, allow_null=True, default=None,
        help_text="Услуга, если клиент просил подобрать на месте и её ещё не выбрали.",
    )
    oil = serializers.UUIDField(
        required=False, allow_null=True, default=None,
        help_text="То же по старому API: масло вместо услуги. Устарело.",
    )


class MasterSetServiceSerializer(serializers.Serializer):
    """Услуга, выбранная мастером вместе с клиентом."""

    service = serializers.UUIDField()


class MasterSetOilSerializer(serializers.Serializer):
    """То же по старому API. Устарело: масло ищется среди услуг точки."""

    oil = serializers.UUIDField()


class MasterBookingCreateSerializer(serializers.Serializer):
    """Запись клиента мастером — по звонку или у стойки."""

    phone = serializers.CharField(max_length=32, help_text="Любая запись номера: 8 900…, +7 900…")
    full_name = serializers.CharField(max_length=150)
    car_model = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    car_plate = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    car_id = serializers.UUIDField(
        required=False, allow_null=True, default=None,
        help_text="Машина клиента из /master/walk-in/lookup/. Иначе car_model и car_plate.",
    )
    service_point = serializers.UUIDField()
    service = serializers.UUIDField(
        required=False, allow_null=True, default=None,
        help_text="Услуга из /master/walk-in/services/.",
    )
    oil = serializers.UUIDField(
        required=False, allow_null=True, default=None,
        help_text="Масло вместо услуги — старое окно записи. Устарело.",
    )
    start_at = serializers.DateTimeField(
        help_text="start_at слота из /master/walk-in/slots/ как есть"
    )
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs["service"] and not attrs["oil"]:
            raise serializers.ValidationError({"service": "Выберите услугу."})
        return attrs


class MasterAvailableOilSerializer(AvailableOilSerializer):
    """Масло в наличии глазами мастера — с ценами: из них считается чек.

    Клиентский `AvailableOilSerializer` цен не отдаёт вовсе (решение
    заказчика), поэтому у мастера свой, а не общий с флагом.
    """

    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    work_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    total_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta(AvailableOilSerializer.Meta):
        fields = AvailableOilSerializer.Meta.fields + ("price", "work_price", "total_price")


class ClientLookupSerializer(serializers.Serializer):
    """Кто стоит за номером: подставить имя и машину в окно записи."""

    phone = serializers.CharField()
    found = serializers.BooleanField()
    is_client = serializers.BooleanField()
    full_name = serializers.CharField(allow_blank=True)
    car_model = serializers.CharField(allow_blank=True, help_text="Основная машина")
    car_plate = serializers.CharField(allow_blank=True, help_text="Основная машина")
    cars = CarShortSerializer(many=True, help_text="Все машины клиента, основная первой")


class PointsQuoteSerializer(serializers.Serializer):
    """Окно расчёта у мастера: баланс клиента и сколько можно списать."""

    balance = serializers.DecimalField(max_digits=10, decimal_places=2)
    limit = serializers.DecimalField(max_digits=10, decimal_places=2)
    max_spend = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    max_discount_percent = serializers.IntegerField()


# ----------------------------------------------------------------- услуги
class MasterServiceSerializer(serializers.Serializer):
    """Услуга глазами мастера — с ценой, материалом и остатком."""

    id = serializers.UUIDField(read_only=True)
    category = serializers.UUIDField(source="category_id", read_only=True)
    name = serializers.CharField(max_length=160)
    description = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default=""
    )
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal(0))
    material_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal(0), required=False,
        default=Decimal(0),
        help_text="Часть цены, ушедшая на расходник. Ноль — услуга без материала.",
    )
    work_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    is_limited = serializers.BooleanField(default=False)
    quantity = serializers.IntegerField(min_value=0, max_value=100000, default=0)
    is_active = serializers.BooleanField(default=True)
    sort_order = serializers.IntegerField(min_value=0, max_value=32000, default=100)


class MasterServiceCategorySerializer(serializers.Serializer):
    """Категория точки со своими услугами."""

    id = serializers.UUIDField(read_only=True)
    service_point = serializers.UUIDField(source="service_point_id")
    service_point_name = serializers.CharField(source="service_point.name", read_only=True)
    name = serializers.CharField(max_length=120)
    sort_order = serializers.IntegerField(min_value=0, max_value=32000, default=100)
    is_active = serializers.BooleanField(default=True)
    allow_on_site = serializers.BooleanField(
        default=True,
        help_text="Клиент сможет записаться, не выбрав услугу: мастер перезвонит.",
    )
    journal_kind = serializers.ChoiceField(
        choices=ServiceJournalKind.choices, default=ServiceJournalKind.OTHER,
        help_text="Чем выполненная запись станет в дневнике клиента.",
    )
    services = serializers.SerializerMethodField()

    @extend_schema_field(MasterServiceSerializer(many=True))
    def get_services(self, obj):
        return MasterServiceSerializer(obj.services.all(), many=True).data


class MasterPointShortSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MasterServiceCatalogSerializer(serializers.Serializer):
    """Каталог одним ответом: точки сотрудника и категории с услугами.

    Точки отдельным списком, а не из категорий: на новой точке категорий
    ещё нет, а первую завести как-то надо.
    """

    points = MasterPointShortSerializer(many=True)
    categories = MasterServiceCategorySerializer(many=True)


class MasterCategoryUpdateSerializer(MasterServiceCategorySerializer):
    """Правка категории: точку у категории не меняют — каталог у точки свой."""

    service_point = serializers.UUIDField(source="service_point_id", read_only=True)


class MasterServiceCreateSerializer(MasterServiceSerializer):
    category = serializers.UUIDField()


class MasterAvailableServiceSerializer(serializers.Serializer):
    """Услуга в наличии глазами мастера: с ценой и остатком.

    Клиентский `ServiceSerializer` ни цен, ни остатка не отдаёт вовсе
    (решение заказчика), поэтому у мастера свой, а не общий с флагом.
    """

    id = serializers.UUIDField()
    name = serializers.CharField()
    category = serializers.UUIDField(source="category_id")
    category_title = serializers.CharField(source="category.name")
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    material_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    available_quantity = serializers.IntegerField(
        allow_null=True, help_text="Пусто — у услуги не ведётся остаток"
    )


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


class MasterCatalogSerializer(serializers.Serializer):
    points = MasterPointShortSerializer(many=True)
    oils = MasterOilSerializer(many=True)


class NoShowSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class LiveDraftSerializer(serializers.ModelSerializer):
    """Кто прямо сейчас записывается. Полезно, чтобы понимать нагрузку."""

    client_name = serializers.CharField(source="user.display_name", read_only=True)
    client_phone = serializers.CharField(source="user.phone", read_only=True)
    service_title = serializers.SerializerMethodField(
        help_text="Что выбрано: услуга, «подберём на месте» или пока только категория"
    )
    oil_title = serializers.SerializerMethodField(help_text="Устарело: то же, что service_title")
    seconds_left = serializers.IntegerField(read_only=True)

    class Meta:
        model = BookingDraft
        fields = (
            "id",
            "step",
            "client_name",
            "client_phone",
            "service_title",
            "oil_title",
            "slot_start",
            "seconds_left",
            "created_at",
        )

    def get_service_title(self, obj: BookingDraft) -> str | None:
        category = obj.service_category.name if obj.service_category_id else ""
        if obj.on_site:
            return "Подберём на месте" + (f" · {category}" if category else "")
        if obj.service_id:
            return obj.service.name
        return f"{category} · услуга не выбрана" if category else None

    def get_oil_title(self, obj: BookingDraft) -> str | None:
        return self.get_service_title(obj)


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
    material_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    work_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    adjustments = serializers.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Правки итога мастером при расчёте: плюс — доплаты, минус — уступки",
    )
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
    category_selected = serializers.IntegerField()
    service_selected = serializers.IntegerField()
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


class MetricsServiceSerializer(serializers.Serializer):
    service_title = serializers.CharField()
    total = serializers.IntegerField()
    completed = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=12, decimal_places=2)


class MetricsClientsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    new = serializers.IntegerField()
    returning = serializers.IntegerField()


class MetricsStockItemSerializer(serializers.Serializer):
    point = serializers.CharField()
    service = serializers.CharField()
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
    top_services = MetricsServiceSerializer(many=True)
    clients = MetricsClientsSerializer()
    stock = MetricsStockSerializer()
    live = MetricsLiveSerializer()


# ----------------------------------------------------------------- звонки
class CallSerializer(serializers.ModelSerializer):
    """Звонок в журнале: зачем, чем кончилось, кто и когда."""

    reason_display = serializers.CharField(source="get_reason_display", read_only=True)
    outcome_display = serializers.CharField(source="get_outcome_display", read_only=True)
    booking_code = serializers.SerializerMethodField()
    service_point_name = serializers.CharField(source="service_point.name", read_only=True)
    actor = serializers.SerializerMethodField()

    class Meta:
        model = BookingCall
        fields = (
            "id",
            "booking",
            "booking_code",
            "client",
            "service_point",
            "service_point_name",
            "reason",
            "reason_display",
            "outcome",
            "outcome_display",
            "callback_at",
            "note",
            "actor",
            "created_at",
        )

    def get_booking_code(self, obj: BookingCall) -> str | None:
        return obj.booking.code if obj.booking_id else None

    def get_actor(self, obj: BookingCall) -> str | None:
        return obj.actor.display_name if obj.actor_id else None


class CallCreateSerializer(serializers.Serializer):
    """Отметка звонка по записи."""

    outcome = serializers.ChoiceField(choices=CallOutcome.choices)
    reason = serializers.ChoiceField(
        choices=CallReason.choices, default=CallReason.OTHER,
        help_text="Зачем звонили — причина из очереди «Кому позвонить»",
    )
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    callback_at = serializers.DateTimeField(
        required=False, allow_null=True, default=None,
        help_text="Только для «перезвонить»: когда, с часовым поясом",
    )


class ClientCallCreateSerializer(CallCreateSerializer):
    """Отметка звонка из карточки клиента — без записи, но с точкой."""

    service_point = serializers.UUIDField()


class CallQueueItemSerializer(serializers.Serializer):
    """Строка очереди «Кому позвонить»."""

    reason = serializers.CharField()
    reason_display = serializers.SerializerMethodField()
    priority = serializers.IntegerField()
    hint = serializers.CharField(help_text="Что выяснить")
    due_at = serializers.DateTimeField(source="sort_at")
    local_time = serializers.SerializerMethodField(
        help_text="Время записи, а у «перезвонить» — назначенное время, в поясе точки"
    )
    booking = serializers.SerializerMethodField()
    booking_code = serializers.SerializerMethodField()
    client = serializers.UUIDField(source="client.id")
    client_name = serializers.SerializerMethodField()
    client_phone = serializers.CharField(source="client.phone")
    service_point = serializers.UUIDField(source="service_point.id")
    service_point_name = serializers.CharField(source="service_point.name")
    category_title = serializers.SerializerMethodField()
    attempts = serializers.IntegerField(help_text="Сколько раз не дозвонились по этой причине")
    last_call = serializers.SerializerMethodField()

    def get_reason_display(self, obj) -> str:
        return CallReason(obj.reason).label

    def get_local_time(self, obj) -> str:
        moment = obj.callback.callback_at if obj.callback else obj.booking.start_at
        return moment.astimezone(obj.service_point.tz).strftime("%d.%m.%Y %H:%M")

    def get_booking(self, obj) -> str | None:
        return str(obj.booking.pk) if obj.booking else None

    def get_booking_code(self, obj) -> str | None:
        return obj.booking.code if obj.booking else None

    def get_client_name(self, obj) -> str:
        if obj.booking and obj.booking.client_name:
            return obj.booking.client_name
        return obj.client.full_name

    def get_category_title(self, obj) -> str:
        return obj.booking.category_title if obj.booking else ""

    @extend_schema_field(CallSerializer(allow_null=True))
    def get_last_call(self, obj):
        return CallSerializer(obj.last_call).data if obj.last_call else None
