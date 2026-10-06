from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.garage.views import CarViewSet

app_name = "garage"

router = DefaultRouter(use_regex_path=False)
router.register("cars", CarViewSet, basename="car")

urlpatterns = [path("", include(router.urls))]
