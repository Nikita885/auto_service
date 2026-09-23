from rest_framework import serializers

from apps.booking.constants import STEP_ORDER, DraftStep
from apps.booking.models import Booking, BookingDraft, BookingStatusLog
from apps.catalog.serializers import OilSerializer, ServicePointSerializer


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
            "oil",
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
            done = STEP_ORDER.index(obj.step)
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


class SelectOilSerializer(serializers.Serializer):
    oil_id = serializers.UUIDField()


class SelectSlotSerializer(serializers.Serializer):
    start_at = serializers.DateTimeField(
        help_text="Начало слота в ISO 8601 с таймзоной, ровно как пришло из /slots/."
    )


class ConfirmDraftSerializer(serializers.Serializer):
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True)


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
    """Запись глазами клиента."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    service_point = ServicePointSerializer(read_only=True)
    can_cancel = serializers.BooleanField(
        source="is_cancellable_by_client", read_only=True
    )
    paid_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Booking
        fields = (
            "id",
            "code",
            "status",
            "status_display",
            "service_point",
            "oil_title",
            "start_at",
            "end_at",
            "oil_price",
            "work_price",
            "total_price",
            "points_spent",
            "paid_amount",
            "client_comment",
            "cancel_reason",
            "cancelled_at",
            "can_cancel",
            "created_at",
        )


class BookingDetailSerializer(BookingSerializer):
    oil = OilSerializer(read_only=True)
    status_logs = BookingStatusLogSerializer(many=True, read_only=True)

    class Meta(BookingSerializer.Meta):
        fields = BookingSerializer.Meta.fields + ("oil", "status_logs")
