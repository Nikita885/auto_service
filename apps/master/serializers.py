from rest_framework import serializers

from apps.booking.models import Booking, BookingDraft


class MasterBookingSerializer(serializers.ModelSerializer):
    """Запись глазами мастера: видно клиента, машину и масло.

    Здесь телефон отдаётся полностью — мастеру нужно позвонить клиенту,
    если тот опаздывает.
    """

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    service_point_name = serializers.CharField(source="service_point.name", read_only=True)
    local_time = serializers.SerializerMethodField()

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
