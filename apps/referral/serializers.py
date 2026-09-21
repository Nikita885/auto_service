from rest_framework import serializers


class ReferralSummarySerializer(serializers.Serializer):
    """Экран реферальной программы одним ответом.

    Все поля необязательные: при выключенной программе приходит только
    `enabled: false`, и приложение прячет раздел целиком.
    """

    enabled = serializers.BooleanField()
    code = serializers.CharField(required=False)
    invite_url = serializers.URLField(required=False)
    balance = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    max_discount_percent = serializers.IntegerField(required=False)
    level_percents = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    attached = serializers.BooleanField(required=False)
    sponsor_code = serializers.CharField(required=False, allow_blank=True)
    invited_count = serializers.IntegerField(required=False)
    line_counts = serializers.ListField(child=serializers.IntegerField(), required=False)
    earned_total = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )
    spent_total = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )


class PointsEntrySerializer(serializers.Serializer):
    """Строка журнала баллов.

    `percent` и `level` — снимок на момент начисления: ставки меняются в
    `.env`, а история переписываться не должна.
    """

    id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    kind = serializers.CharField()
    kind_display = serializers.CharField(source="get_kind_display")
    level = serializers.IntegerField(allow_null=True)
    percent = serializers.DecimalField(
        max_digits=5, decimal_places=2, allow_null=True
    )
    base_amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
    booking_code = serializers.CharField(source="booking.code", default="")
    comment = serializers.CharField()
    created_at = serializers.DateTimeField()


class InvitedSerializer(serializers.Serializer):
    name = serializers.CharField()
    phone_masked = serializers.CharField()
    joined_at = serializers.DateTimeField()
    line = serializers.IntegerField()
    earned_from = serializers.DecimalField(max_digits=10, decimal_places=2)


class AttachSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=16, trim_whitespace=True)
