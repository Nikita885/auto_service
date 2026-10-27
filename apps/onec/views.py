from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsMaster
from apps.onec.authentication import IsOneC, OneCKeyAuthentication
from apps.onec.serializers import AckSerializer, ChangesSerializer
from apps.onec.services import sync as sync_service


class OneCView(APIView):
    authentication_classes = [OneCKeyAuthentication]
    permission_classes = [IsOneC]
    throttle_scope = "onec"


@extend_schema(tags=["Обмен с 1С"])
class OneCPingView(OneCView):
    @extend_schema(summary="Проверка связи и ключа", responses={200: dict})
    def get(self, request: Request) -> Response:
        return Response({
            "ok": True,
            "user": request.user.full_name or request.user.phone,
            "server_time": timezone.now().isoformat(),
            "batch_size": settings.ONEC["BATCH_SIZE"],
        })


@extend_schema(tags=["Обмен с 1С"])
class OneCPendingView(OneCView):
    @extend_schema(
        summary="Записи для выгрузки в 1С",
        description="Новые и изменённые на сайте записи — целиком, самые давние правки "
        "первыми. `more` — за этой пачкой есть ещё. Время — местное время точки.",
        responses={200: dict},
    )
    def get(self, request: Request) -> Response:
        rows, more = sync_service.pending(request.user)
        return Response({
            "bookings": [sync_service.snapshot(booking) for booking in rows],
            "more": more,
        })


@extend_schema(tags=["Обмен с 1С"])
class OneCLinkedView(OneCView):
    @extend_schema(
        summary="Записи, заявки которых 1С сверяет с сайтом",
        description="id выгруженных записей — живых и недавних. По ним 1С собирает "
        "заявки и заказ-наряды для `changes`.",
        responses={200: dict},
    )
    def get(self, request: Request) -> Response:
        return Response({"ids": sync_service.linked(request.user)})


@extend_schema(tags=["Обмен с 1С"])
class OneCAckView(OneCView):
    @extend_schema(
        request=AckSerializer,
        summary="1С записала заявки",
        description="`version` — та, что пришла в выгрузке. С `error` запись тоже "
        "считается выгруженной, ошибка видна в 1С и в Django-админке.",
        responses={200: dict},
    )
    def post(self, request: Request) -> Response:
        payload = AckSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        accepted = sync_service.ack(request.user, payload.validated_data["items"])
        return Response({"accepted": accepted})


@extend_schema(tags=["Обмен с 1С"])
class OneCChangesView(OneCView):
    @extend_schema(
        request=ChangesSerializer,
        summary="Правки из 1С",
        description="Заявка и заказ-наряд по каждой записи. Сайт применяет только "
        "изменившееся с прошлого обмена (по версиям 1С): перенос, отмену, «в работе» "
        "по проведённому заказ-наряду, «выполнена» по закрытому или оплаченному. "
        "Не принятая правка возвращается ошибкой, а запись уходит в 1С заново.",
        responses={200: dict},
    )
    def post(self, request: Request) -> Response:
        payload = ChangesSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        results = sync_service.apply_changes(request.user, payload.validated_data["items"])
        return Response({"results": results})


@extend_schema(tags=["Обмен с 1С"])
class OneCResendView(APIView):
    """Сотрудник просит выгрузить запись в 1С заново — из панели или 1С."""

    authentication_classes = [OneCKeyAuthentication, *APIView.authentication_classes]
    permission_classes = [IsMaster]

    @extend_schema(summary="Выгрузить запись в 1С заново", request=None, responses={200: dict})
    def post(self, request: Request, booking_id) -> Response:
        sync_service.resend(request.user, booking_id)
        return Response({"ok": True})
