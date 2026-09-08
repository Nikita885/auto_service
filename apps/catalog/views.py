from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.permissions import AllowAny

from apps.catalog.models import ServicePoint
from apps.catalog.serializers import ServicePointSerializer


@extend_schema(tags=["Каталог"])
class ServicePointViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Адреса сервиса. Открыты без авторизации: их видно ещё до входа."""

    serializer_class = ServicePointSerializer
    permission_classes = [AllowAny]
    pagination_class = None
    queryset = ServicePoint.objects.filter(is_active=True)
