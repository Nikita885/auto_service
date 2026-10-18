from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.models import (
    CarMake,
    CarModel,
    Oil,
    Service,
    ServiceCategory,
    ServicePoint,
)


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


class ServiceSerializer(serializers.ModelSerializer):
    """Услуга глазами клиента — без цен и без остатка.

    Цен клиенту не показываем нигде (решение заказчика), и убраны они из
    ответа, а не только из вёрстки: спрятанное в интерфейсе, но лежащее в
    JSON — та же публикация. Остаток — внутренняя кухня: сколько канистр
    на полке, клиента не касается.
    """

    class Meta:
        model = Service
        fields = ("id", "name", "description")


class ServiceCategorySerializer(serializers.ModelSerializer):
    """Категория точки со списком доступных услуг.

    `services` подкладывает сервис доступности (`stock.available_categories`):
    в ответе только то, что реально можно выбрать сейчас.
    """

    services = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        # `journal_kind` — только чтобы приложение нарисовало значок
        # категории (масло, шины, мойка); цен и остатков здесь нет.
        fields = ("id", "name", "journal_kind", "allow_on_site", "services")

    @extend_schema_field(ServiceSerializer(many=True))
    def get_services(self, obj: ServiceCategory):
        services = getattr(obj, "available_services", None)
        if services is None:
            services = [row for row in obj.services.all() if row.is_active]
        return ServiceSerializer(services, many=True).data


class OilSerializer(serializers.ModelSerializer):
    """Масло глазами клиента — без цен.

    Цен клиенту не показываем нигде (решение заказчика), и убраны они из
    ответа, а не только из вёрстки: спрятанное в интерфейсе, но лежащее в
    JSON — та же публикация. Мастер видит цены в своих сериализаторах.
    """

    oil_type_display = serializers.CharField(source="get_oil_type_display", read_only=True)
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
