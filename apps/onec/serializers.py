from rest_framework import serializers


class AckItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    version = serializers.CharField(max_length=64)
    request_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    request_version = serializers.CharField(max_length=64, required=False, allow_blank=True)
    error = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class AckSerializer(serializers.Serializer):
    items = AckItemSerializer(many=True, max_length=500)


class RequestStateSerializer(serializers.Serializer):
    """Заявка на ремонт, как она лежит в 1С."""

    number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    version = serializers.CharField(max_length=64)
    # Местное время точки без пояса: в датах 1С пояса нет.
    start = serializers.CharField(max_length=32, required=False, allow_blank=True)
    deleted = serializers.BooleanField(default=False)


class OrderLineSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, allow_blank=True)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class OrderStateSerializer(serializers.Serializer):
    """Заказ-наряд, созданный в 1С на основании заявки."""

    ref = serializers.UUIDField()
    number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    version = serializers.CharField(max_length=64)
    state = serializers.CharField(max_length=64, required=False, allow_blank=True)
    posted = serializers.BooleanField(default=False)
    deleted = serializers.BooleanField(default=False)
    total = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    paid_total = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    receipt_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    paid_at = serializers.CharField(max_length=32, required=False, allow_blank=True)
    lines = OrderLineSerializer(many=True, required=False, max_length=200)


class ChangeItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    request = RequestStateSerializer(required=False)
    order = OrderStateSerializer(required=False, allow_null=True)


class ChangesSerializer(serializers.Serializer):
    items = ChangeItemSerializer(many=True, max_length=500)
