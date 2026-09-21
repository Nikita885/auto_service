from rest_framework import serializers

from apps.catalog.models import CarMake, CarModel, Oil, ServicePoint


class ServicePointSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePoint
        fields = (
            "id",
            "name",
            "address",
            "phone",
            "latitude",
            "longitude",
            "timezone",
            "opens_at",
            "closes_at",
            "workdays",
            "slot_minutes",
            "posts_count",
        )


class OilSerializer(serializers.ModelSerializer):
    oil_type_display = serializers.CharField(source="get_oil_type_display", read_only=True)
    total_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    title = serializers.CharField(source="__str__", read_only=True)

    class Meta:
        model = Oil
        fields = (
            "id",
            "title",
            "brand",
            "name",
            "viscosity",
            "oil_type",
            "oil_type_display",
            "volume_liters",
            "price",
            "work_price",
            "total_price",
            "description",
        )


class AvailableOilSerializer(OilSerializer):
    """Масло с остатком на конкретной точке с учётом уже занятых канистр."""

    available_quantity = serializers.IntegerField(read_only=True)

    class Meta(OilSerializer.Meta):
        fields = OilSerializer.Meta.fields + ("available_quantity",)


class SlotSerializer(serializers.Serializer):
    start_at = serializers.DateTimeField()
    end_at = serializers.DateTimeField()
    local_time = serializers.CharField()
    free_posts = serializers.IntegerField()


class CarMakeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CarMake
        fields = ("id", "name")


class CarModelSerializer(serializers.ModelSerializer):
    make_name = serializers.CharField(source="make.name", read_only=True)
    # Готовая строка «марка + модель»: ровно её приложение кладёт в профиль,
    # и склеивать её на клиенте значит однажды склеить иначе.
    title = serializers.CharField(source="__str__", read_only=True)

    class Meta:
        model = CarModel
        fields = ("id", "name", "make_name", "title")
