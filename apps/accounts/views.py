from contextlib import suppress
from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services
from apps.accounts.serializers import (
    AccountDeletionResponseSerializer,
    AccountDeletionSerializer,
    AuthResponseSerializer,
    CallPendingSerializer,
    CallStatusSerializer,
    LogoutSerializer,
    OtpRequestResponseSerializer,
    OtpRequestSerializer,
    OtpVerifySerializer,
    ProfileUpdateSerializer,
    StaffLoginSerializer,
    UserSerializer,
)
from apps.common.net import client_ip


def _auth_payload(result) -> dict:
    """Ответ успешного входа — один на код, звонок и пароль сотрудника."""
    return {
        "access": result.access,
        "refresh": result.refresh,
        "is_new_user": result.is_new_user,
        "user": UserSerializer(result.user).data,
        "invite": result.invite,
    }


class OtpRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "otp_request"

    @extend_schema(
        request=OtpRequestSerializer,
        responses={200: OtpRequestResponseSerializer},
        summary="Запросить код входа: звонком, после неудачных звонков — SMS",
        description=(
            "По умолчанию звонок: код — последние 4 цифры входящего номера. "
            "После OTP_CALLS_BEFORE_SMS звонков без входа в ответе "
            "sms_available=true, и следующий код можно попросить в SMS "
            "(channel=sms). Номерам сотрудников — 403 staff_use_password."
        ),
        auth=[],
    )
    def post(self, request: Request) -> Response:
        payload = OtpRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        challenge = services.request_otp(
            payload.validated_data["phone"],
            ip=client_ip(request),
            channel=payload.validated_data["channel"],
        )
        data = asdict(challenge)
        if data.get("debug_code") is None:
            data.pop("debug_code", None)
        return Response(data, status=status.HTTP_200_OK)


class OtpCallStatusView(APIView):
    """Обратный звонок: позвонил ли клиент. Приложение спрашивает раз в 2 с."""

    permission_classes = [AllowAny]
    throttle_scope = "otp_poll"

    @extend_schema(
        request=CallStatusSerializer,
        responses={200: AuthResponseSerializer, 202: CallPendingSerializer},
        summary="Статус обратного звонка (OTP_MODE=verificahub)",
        description=(
            "202 {status: pending} — звонка ещё нет, спросите снова через 2 с. "
            "200 — номер подтверждён, в ответе токены, как у otp/verify. "
            "410 otp_expired / 400 otp_call_failed — начните вход заново."
        ),
        auth=[],
    )
    def post(self, request: Request) -> Response:
        payload = CallStatusSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = services.check_call(
            payload.validated_data["phone"],
            payload.validated_data["session"],
            invite=payload.validated_data.get("invite", ""),
        )
        if result is None:
            return Response({"status": "pending"}, status=status.HTTP_202_ACCEPTED)
        return Response(_auth_payload(result))


class OtpVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "otp_verify"

    @extend_schema(
        request=OtpVerifySerializer,
        responses={200: AuthResponseSerializer},
        summary="Проверить код и получить JWT",
        description=(
            "Если аккаунта с таким телефоном ещё нет — он создаётся здесь же, "
            "поле is_new_user подскажет клиенту, что стоит попросить имя."
        ),
        auth=[],
    )
    def post(self, request: Request) -> Response:
        payload = OtpVerifySerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        result = services.verify_otp(
            payload.validated_data["phone"],
            payload.validated_data["code"],
            invite=payload.validated_data.get("invite", ""),
        )
        return Response(_auth_payload(result), status=status.HTTP_200_OK)


class StaffLoginView(APIView):
    """Вход сотрудника в панели мастера и администратора — по паролю."""

    permission_classes = [AllowAny]
    throttle_scope = "staff_login"

    @extend_schema(
        request=StaffLoginSerializer,
        responses={200: AuthResponseSerializer},
        summary="Вход сотрудника по паролю",
        description="Клиенту и неверному паролю — одинаково 400 invalid_credentials.",
        auth=[],
    )
    def post(self, request: Request) -> Response:
        payload = StaffLoginSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        result = services.staff_login(
            payload.validated_data["phone"], payload.validated_data["password"]
        )
        return Response(_auth_payload(result))


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: UserSerializer}, summary="Мой профиль")
    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)


    @extend_schema(
        request=ProfileUpdateSerializer,
        responses={200: UserSerializer},
        summary="Обновить профиль",
    )
    def patch(self, request: Request) -> Response:
        payload = ProfileUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)

        user = services.update_profile(request.user, **payload.validated_data)
        return Response(UserSerializer(user).data)

class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "logout"

    @extend_schema(request=LogoutSerializer, responses={204: None}, summary="Завершить сессию")
    def post(self, request):
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.tokens import RefreshToken

        raw = request.data.get("refresh", "")
        if isinstance(raw, str) and 0 < len(raw) <= 4096:
            with suppress(TokenError):
                RefreshToken(raw).blacklist()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccountDeletionView(APIView):
    from apps.common.permissions import IsClient

    permission_classes = [IsClient]
    throttle_scope = "account_delete"

    @extend_schema(
        request=AccountDeletionSerializer, responses={202: AccountDeletionResponseSerializer},
        summary="Запросить удаление аккаунта и данных",
    )
    def post(self, request):
        from apps.accounts.models import AccountDeletionRequest
        from apps.common.exceptions import ValidationError

        if request.data.get("confirm") is not True:
            raise ValidationError("Подтвердите запрос на удаление", code="confirmation_required")
        item, _ = AccountDeletionRequest.objects.get_or_create(user=request.user)
        return Response({"status": "requested", "requested_at": item.created_at}, status=202)
