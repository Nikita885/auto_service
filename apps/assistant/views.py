from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assistant.serializers import (
    AssistantAnswerSerializer,
    AssistantAskSerializer,
    AssistantStatusSerializer,
)
from apps.assistant.services import assistant as assistant_service
from apps.common.exceptions import ValidationError
from apps.common.permissions import IsClient


@extend_schema(tags=["Подсказчик"])
class AssistantView(APIView):
    """Подсказчик в записи: помогает выбрать услугу точки по описанию."""

    permission_classes = [IsClient]

    @extend_schema(
        parameters=[
            OpenApiParameter("service_point", str, required=True, description="UUID точки")
        ],
        responses={200: AssistantStatusSerializer},
        summary="Доступен ли подсказчик",
        description="Кнопку показывают, только если `available`: провайдер настроен, "
        "месячный потолок трат не выбран и у клиента остались вопросы на сегодня.",
    )
    def get(self, request: Request) -> Response:
        point_id = request.query_params.get("service_point")
        if not point_id:
            raise ValidationError("Укажите адрес", code="point_required")
        return Response(AssistantStatusSerializer(
            assistant_service.status(request.user, point_id)
        ).data)

    @extend_schema(
        request=AssistantAskSerializer,
        responses={200: AssistantAnswerSerializer},
        summary="Спросить подсказчика",
        description=(
            "Ответ и, если понятно, что нужно, — категория и услуга точки (или «мастер "
            "подберёт на месте»). Запись не меняется: предложение выбирают обычными "
            "шагами черновика. Лимиты — не ошибка: ответ с `handoff` и текстом "
            "«дальше с мастером»."
        ),
    )
    def post(self, request: Request) -> Response:
        payload = AssistantAskSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        answer = assistant_service.ask(
            request.user, data["service_point"],
            message=data["message"], chat=data["chat"], history=data["history"],
        )
        return Response(AssistantAnswerSerializer(answer).data)
