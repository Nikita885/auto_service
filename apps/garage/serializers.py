from rest_framework import serializers

from apps.garage.models import Car


class CarSerializer(serializers.ModelSerializer):
    model_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Car
        fields = (
            "id", "title", "plate", "year", "mileage", "vin", "model_id",
            "is_primary", "created_at",
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


class CarShortSerializer(serializers.ModelSerializer):
    """Машина в чужих ответах: в записи, в подсказке мастеру."""

    class Meta:
        model = Car
        fields = ("id", "title", "plate", "is_primary")
        read_only_fields = fields
