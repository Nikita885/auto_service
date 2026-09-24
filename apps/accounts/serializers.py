from rest_framework import serializers

from apps.accounts.models import User


class OtpRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20, help_text="+7 900 123-45-67")


class OtpRequestResponseSerializer(serializers.Serializer):
    phone = serializers.CharField()
    expires_at = serializers.DateTimeField()
    resend_after_seconds = serializers.IntegerField()
    debug_code = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Только при OTP_DEBUG_EXPOSE_CODE=True. В проде не приходит.",
    )


class OtpVerifySerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    code = serializers.CharField(min_length=4, max_length=8, trim_whitespace=True)
    invite = serializers.CharField(
        max_length=16, required=False, allow_blank=True,
        help_text="Код приглашения из ссылки или QR — клиент привязывается сразу при входе.",
    )


class InviteResultSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["attached", "rejected"])
    inviter_name = serializers.CharField(required=False)
    code = serializers.CharField(required=False)
    message = serializers.CharField(required=False)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "phone",
            "full_name",
            "role",
            "car_model",
            "car_plate",
            "date_joined",
        )
        read_only_fields = ("id", "phone", "role", "date_joined")


class ProfileUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    car_model = serializers.CharField(max_length=120, required=False, allow_blank=True)
    car_plate = serializers.CharField(max_length=16, required=False, allow_blank=True)


class AuthResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    is_new_user = serializers.BooleanField()
    user = UserSerializer()
    invite = InviteResultSerializer(required=False, allow_null=True)
