from decimal import Decimal

from rest_framework import serializers


class WorkplaceOrderLineSerializer(serializers.Serializer):
    ref = serializers.UUIDField(required=False, allow_null=True)
    line_id = serializers.UUIDField(required=False, allow_null=True)
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal(0), required=False
    )
    name = serializers.CharField(max_length=255)
    kind = serializers.ChoiceField(choices=("work", "material"))
    unit = serializers.CharField(max_length=20, default="шт.")
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal(0))


class OrderSaveSerializer(serializers.Serializer):
    revision = serializers.IntegerField(min_value=1)
    order_ref = serializers.UUIDField(required=False, allow_null=True)
    order_number = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    lines = WorkplaceOrderLineSerializer(many=True, allow_empty=False, max_length=500)
    recommendations = serializers.CharField(max_length=4000, allow_blank=True, default="")


class CheckoutPrepareSerializer(serializers.Serializer):
    revision = serializers.IntegerField(min_value=1)
    checkout_id = serializers.UUIDField()
    points = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal(0))
    cash = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal(0))
    card = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal(0))


class PointsQuoteSerializer(serializers.Serializer):
    total = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class ReceiptSerializer(serializers.Serializer):
    number = serializers.CharField(max_length=32)
    shift = serializers.CharField(max_length=32, required=False, allow_blank=True)
    fiscal_drive = serializers.CharField(max_length=32, required=False, allow_blank=True)
    fiscal_document = serializers.CharField(max_length=32, required=False, allow_blank=True)
    fiscal_sign = serializers.CharField(max_length=32, required=False, allow_blank=True)


class CheckoutEventSerializer(serializers.Serializer):
    checkout_id = serializers.UUIDField()
    event = serializers.ChoiceField(
        choices=(
            "card_started",
            "card_succeeded",
            "card_declined",
            "cash_confirmed",
            "fiscal_started",
            "fiscal_succeeded",
            "review",
            "cancel",
        )
    )
    bank_reference = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    receipt = ReceiptSerializer(required=False)
