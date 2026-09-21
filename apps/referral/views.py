"""API реферальной программы для клиентского приложения.

Вьюхи тонкие: разобрать вход, позвать сервис, отдать результат. Все
подсчёты — в `services/profile.py`, размещение в матрице — в
`services/tree.py`.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsClient
from apps.referral.models import PointsEntry
from apps.referral.serializers import (
    AttachSerializer,
    InvitedSerializer,
    PointsEntrySerializer,
    ReferralSummarySerializer,
)
from apps.referral.services import profile as profile_service
from apps.referral.services import tree as tree_service


class _ClientView(APIView):
    """Общая база: программа только для клиентов.

    Мастеру и администратору код приглашения не нужен, а узел в матрице на
    сотруднике означал бы, что сервис начисляет баллы сам себе.
    """

    permission_classes = [IsClient]

    @staticmethod
    def _summary(user) -> Response:
        """Сводка, пропущенная через сериализатор.

        Именно через него, а не словарём напрямую: суммы в словаре — это
        Decimal, и JSON-рендерер отдал бы их числами. Схема обещает
        строки, а клиент на числах с плавающей точкой однажды покажет
        «199.99999».
        """
        return Response(ReferralSummarySerializer(profile_service.summary(user)).data)


@extend_schema(tags=["Реферальная программа"])
class ReferralSummaryView(_ClientView):
    @extend_schema(
        responses={200: ReferralSummarySerializer},
        summary="Моя реферальная программа",
        description=(
            "Код приглашения, ссылка, баланс баллов и счётчики по линиям. "
            "При выключенной программе приходит только enabled=false."
        ),
    )
    def get(self, request: Request) -> Response:
        return self._summary(request.user)


@extend_schema(tags=["Реферальная программа"])
class ReferralAttachView(_ClientView):
    @extend_schema(
        request=AttachSerializer,
        responses={200: ReferralSummarySerializer},
        summary="Принять приглашение по коду",
        description=(
            "Привязка одноразовая: сменить пригласившего нельзя, иначе "
            "кто-то уже получил бы баллы за чужого клиента."
        ),
    )
    def post(self, request: Request) -> Response:
        payload = AttachSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        tree_service.attach(request.user, payload.validated_data["code"])
        return self._summary(request.user)


@extend_schema(tags=["Реферальная программа"])
class PointsHistoryView(ListAPIView):
    """История баллов: начисления, списания, корректировки."""

    permission_classes = [IsClient]
    serializer_class = PointsEntrySerializer
    # Пустой queryset нужен генератору схемы: он определяет модель по этому
    # полю, а `get_queryset` при сборке OpenAPI вызывается без живого
    # пользователя и падает на попытке найти его узел.
    queryset = PointsEntry.objects.none()

    def get_queryset(self):
        node = tree_service.ensure_node(self.request.user)
        return profile_service.entries(node)

    @extend_schema(summary="История баллов")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


@extend_schema(tags=["Реферальная программа"])
class InvitedListView(_ClientView):
    @extend_schema(
        responses={200: InvitedSerializer(many=True)},
        summary="Кого я пригласил",
    )
    def get(self, request: Request) -> Response:
        owner = tree_service.ensure_node(request.user)
        cards = [
            profile_service.invited_card(node, owner)
            for node in profile_service.invited(owner)
        ]
        return Response(InvitedSerializer(cards, many=True).data)


@extend_schema(tags=["Реферальная программа"])
class ReferralCodeCheckView(APIView):
    """Проверка кода до входа: страница-приглашение показывает, чей он.

    Открыта без авторизации намеренно — человек переходит по ссылке ещё до
    того, как поставил приложение. Наружу уходит только имя пригласившего:
    по коду не должно быть видно ни телефона, ни размера ветки.
    """

    permission_classes = []
    authentication_classes = []
    throttle_scope = "referral_check"

    @extend_schema(
        responses={200: dict},
        summary="Чей это код приглашения",
        auth=[],
    )
    def get(self, request: Request, code: str) -> Response:
        node = tree_service.find_by_code(code)
        return Response(
            {"code": node.code, "inviter_name": node.user.full_name or "Клиент"}
        )
