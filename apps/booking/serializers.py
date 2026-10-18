from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.booking.constants import LEGACY_STEPS, STEP_ORDER, BookingStatus, DraftStep
from apps.booking.models import Booking, BookingDraft, BookingStatusLog
from apps.catalog.serializers import (
    OilSerializer,
    ServiceCategorySerializer,
    ServicePointSerializer,
    ServiceSerializer,
)
from apps.garage.serializers import CarShortSerializer


class BookingDraftSerializer(serializers.ModelSerializer):
    """Состояние процесса записи «как есть».

    Отдаётся и по REST, и в WebSocket одним и тем же кодом — клиент
    разбирает один формат независимо от канала.
    """

    step_display = serializers.CharField(source="get_step_display", read_only=True)
    seconds_left = serializers.IntegerField(read_only=True)
    next_action = serializers.CharField(read_only=True, allow_null=True)
    is_alive = serializers.BooleanField(read_only=True)
    progress = serializers.SerializerMethodField()
    service_point = ServicePointSerializer(read_only=True)
    service_category = ServiceCategorySerializer(read_only=True)
    service = ServiceSerializer(read_only=True)
    oil = OilSerializer(read_only=True)
    slot_end = serializers.DateTimeField(read_only=True)
    booking_id = serializers.SerializerMethodField()

    class Meta:
        model = BookingDraft
        fields = (
            "id",
            "step",
            "step_display",
            "next_action",
            "progress",
            "is_open",
            "is_alive",
            "close_reason",
            "service_point",
            "service_category",
            "service",
            "on_site",
            # Поля масла остаются в ответе, пока обновляются приложения:
            # их читает прежняя версия экрана записи.
            "oil",
            "oil_on_site",
            "slot_start",
            "slot_end",
            "expires_at",
            "seconds_left",
            "booking_id",
            "created_at",
        )

    def get_booking_id(self, obj: BookingDraft) -> str | None:
        return str(obj.booking_id) if obj.booking_id else None

    def get_progress(self, obj: BookingDraft) -> dict:
        """Сколько шагов пройдено — чтобы UI рисовал прогресс без логики."""
        try:
            done = STEP_ORDER.index(LEGACY_STEPS.get(obj.step, obj.step))
        except ValueError:
            done = len(STEP_ORDER) if obj.step == DraftStep.CONFIRMED else 0
        return {"completed": done, "total": len(STEP_ORDER)}


class StartDraftSerializer(serializers.Serializer):
    restart = serializers.BooleanField(
        default=False,
        help_text="True — выбросить незавершённый черновик и начать заново.",
    )


class SelectPointSerializer(serializers.Serializer):
    service_point_id = serializers.UUIDField()


class SelectCategorySerializer(serializers.Serializer):
    category_id = serializers.UUIDField()


class SelectServiceSerializer(serializers.Serializer):
    service_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    on_site = serializers.BooleanField(
        default=False,
        help_text="True — «подберите на месте»: без услуги, мастер перезвонит. "
        "Тогда service_id не нужен.",
    )

    def validate(self, attrs):
        if not attrs["on_site"] and not attrs["service_id"]:
            raise serializers.ValidationError(
                {"service_id": "Выберите услугу или «подберите на месте»."}
            )
        return attrs


class SelectOilSerializer(serializers.Serializer):
    oil_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    on_site = serializers.BooleanField(
        default=False,
        help_text="True — «подберите на месте»: без масла, мастер перезвонит. "
        "Тогда oil_id не нужен.",
    )

    def validate(self, attrs):
        if not attrs["on_site"] and not attrs["oil_id"]:
            raise serializers.ValidationError(
                {"oil_id": "Выберите масло или «подберите на месте»."}
            )
        return attrs


class SelectSlotSerializer(serializers.Serializer):
    start_at = serializers.DateTimeField(
        help_text="Начало слота в ISO 8601 с таймзоной, ровно как пришло из /slots/."
    )


class ConfirmDraftSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True)
    car_id = serializers.UUIDField(
        required=False, allow_null=True,
        help_text="Своя машина из /garage/cars/. Не передана — основная.",
    )


class RescheduleSerializer(serializers.Serializer):
    start_at = serializers.DateTimeField(
        help_text="Начало слота в ISO 8601 с таймзоной, ровно как пришло из /slots/."
    )


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class BookingStatusLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = BookingStatusLog
        fields = ("id", "from_status", "to_status", "actor_name", "comment", "created_at")

    def get_actor_name(self, obj: BookingStatusLog) -> str | None:
        return obj.actor.display_name if obj.actor_id else None


class BookingSerializer(serializers.ModelSerializer):
    """Запись глазами клиента.

    Цен до визита клиент не видит (решение заказчика): ни цены масла, ни
    работы, ни суммы записи в ответе нет. После выполнения — итог, который
    он заплатил, и как он оплачен: это его чек, а не прайс.
    """

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    service_point = ServicePointSerializer(read_only=True)
    can_cancel = serializers.BooleanField(
        source="is_cancellable_by_client", read_only=True
    )
    # Перенос разрешён ровно тогда же, когда отмена: это отмена старого
    # времени. Отдельное поле — чтобы приложение не знало этого правила.
    can_reschedule = serializers.BooleanField(
        source="is_cancellable_by_client", read_only=True
    )
    car = CarShortSerializer(read_only=True, allow_null=True)
    final_price = serializers.SerializerMethodField(
        help_text="Итог к оплате — только у выполненной записи, иначе null"
    )
    paid_amount = serializers.SerializerMethodField(
        help_text="Сколько заплачено деньгами — только у выполненной записи"
    )
    oil_on_site = serializers.SerializerMethodField(
        help_text="Услугу подберут на месте: мастер перезвонит и выберет её вместе с клиентом"
    )
    services = serializers.SerializerMethodField(
        help_text="Услуги записи — только названия: цен клиенту не показываем"
    )
    category_kind = serializers.SerializerMethodField(
        help_text="Вид категории (oil, tires, wash, service, other) — для значка в приложении"
    )

    class Meta:
        model = Booking
        fields = (
            "id",
            "code",
            "status",
            "status_display",
            "service_point",
            "category_title",
            "category_kind",
            "service_title",
            "services",
            # Прежнее название осталось в ответе, пока обновляются
            # приложения: в нём лежит тот же снимок.
            "oil_title",
            "oil_on_site",
            "start_at",
            "end_at",
            "car",
            "car_model",
            "car_plate",
            "final_price",
            "points_spent",
            "paid_amount",
            "client_comment",
            "cancel_reason",
            "cancelled_at",
            "can_cancel",
            "can_reschedule",
            "created_at",
        )


    def get_oil_on_site(self, obj: Booking) -> bool:
        return obj.service_on_site and not obj.items.exists()

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_services(self, obj: Booking) -> list[str]:
        return [item.title for item in obj.items.all()]

    def get_category_kind(self, obj: Booking) -> str:
        category = obj.service_category
        return category.journal_kind if category is not None else "other"

    @staticmethod
    def _completed(obj: Booking) -> bool:
        return obj.status == BookingStatus.COMPLETED

    @extend_schema_field(serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True))
    def get_final_price(self, obj: Booking) -> str | None:
        return f"{obj.charged_price:.2f}" if self._completed(obj) else None

    @extend_schema_field(serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True))
    def get_paid_amount(self, obj: Booking) -> str | None:
        return f"{obj.paid_amount:.2f}" if self._completed(obj) else None


class BookingDetailSerializer(BookingSerializer):
    oil = OilSerializer(read_only=True)
    status_logs = BookingStatusLogSerializer(many=True, read_only=True)

    class Meta(BookingSerializer.Meta):
        fields = BookingSerializer.Meta.fields + ("oil", "status_logs")
