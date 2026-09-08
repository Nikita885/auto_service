from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalog.views import ServicePointViewSet

app_name = "catalog"

router = DefaultRouter()
router.register("service-points", ServicePointViewSet, basename="service-point")

urlpatterns = [path("", include(router.urls))]
