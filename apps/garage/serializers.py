from rest_framework import serializers

from apps.garage.models import Car, EntryKind


class CarSerializer(serializers.ModelSerializer):
    model_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Car
        fields = (
            "id", "title", "plate", "year", "mileage", "vin", "model_id",
            "is_primary", "oil_interval_km", "oil_interval_months",
            "osago_until", "inspection_until", "created_at",
        )
        read_only_fields = fields


class CarWriteSerializer(serializers.Serializer):
    """Вход для добавления и правки. Проверки по смыслу — в сервисе."""

    title = serializers.CharField(max_length=120, required=False, allow_blank=True)
    plate = serializers.CharField(max_length=20, required=False, allow_blank=True)
    year = serializers.IntegerField(required=False, allow_null=True)
    mileage = serializers.IntegerField(required=False, allow_null=True)
    vin = serializers.CharField(max_length=24, required=False, allow_blank=True)
    model_id = serializers.UUIDField(
        required=False, allow_null=True,
        help_text="Модель из /cars/search/ — если клиент выбрал подсказку",
    )
    is_primary = serializers.BooleanField(
        required=False, default=False, help_text="Сделать основным"
    )
    oil_interval_km = serializers.IntegerField(
        required=False, allow_null=True, help_text="Свой интервал замены масла; null — по умолчанию"
    )
    oil_interval_months = serializers.IntegerField(required=False, allow_null=True)
    osago_until = serializers.DateField(required=False, allow_null=True)
    inspection_until = serializers.DateField(required=False, allow_null=True)


class CarShortSerializer(serializers.ModelSerializer):
    """Машина в чужих ответах: в записи, в подсказке мастеру."""

    class Meta:
        model = Car
        fields = ("id", "title", "plate", "is_primary")
        read_only_fields = fields


class EntrySerializer(serializers.Serializer):
    """Строка дневника: своя запись или замена масла у нас (`source`)."""

    id = serializers.CharField()
    kind = serializers.ChoiceField(choices=EntryKind.choices)
    kind_display = serializers.CharField()
    date = serializers.DateField()
    mileage = serializers.IntegerField(allow_null=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    liters = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    full_tank = serializers.BooleanField()
    note = serializers.CharField(allow_blank=True)
    source = serializers.ChoiceField(choices=["manual", "booking"])
    booking_code = serializers.CharField(allow_blank=True)
    editable = serializers.BooleanField()


class EntryWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=EntryKind.choices, required=False)
    date = serializers.DateField(required=False)
    mileage = serializers.IntegerField(required=False, allow_null=True)
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    liters = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, allow_null=True
    )
    full_tank = serializers.BooleanField(required=False)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True)


class ReminderSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["oil", "osago", "inspection", "tires"])
    status = serializers.ChoiceField(choices=["overdue", "soon", "ok", "unknown"])
    due_date = serializers.DateField(allow_null=True)
    left_days = serializers.IntegerField(allow_null=True)
    due_km = serializers.IntegerField(allow_null=True)
    left_km = serializers.IntegerField(allow_null=True)
    season = serializers.CharField(allow_blank=True)
    last_date = serializers.DateField(allow_null=True)


class PeriodSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    by_kind = serializers.SerializerMethodField()
    distance = serializers.IntegerField(allow_null=True)

    def get_by_kind(self, obj) -> list[dict]:
        return [
            {"kind": kind, "kind_display": EntryKind(kind).label, "amount": f"{amount:.2f}"}
            for kind, amount in obj.by_kind.items()
        ]


class FuelSerializer(serializers.Serializer):
    average = serializers.DecimalField(max_digits=6, decimal_places=1, allow_null=True)
    last = serializers.DecimalField(max_digits=6, decimal_places=1, allow_null=True)
    distance = serializers.IntegerField()


class SummarySerializer(serializers.Serializer):
    car = CarSerializer()
    mileage = serializers.IntegerField(allow_null=True)
    oil_interval_km = serializers.IntegerField()
    oil_interval_months = serializers.IntegerField()
    reminders = ReminderSerializer(many=True)
    month = PeriodSerializer()
    year = PeriodSerializer()
    fuel = FuelSerializer()
    recent = EntrySerializer(many=True)
