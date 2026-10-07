from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.garage.views import CarViewSet, EntryViewSet

app_name = "garage"

router = DefaultRouter(use_regex_path=False)
router.register("cars", CarViewSet, basename="car")
router.register("journal", EntryViewSet, basename="entry")

urlpatterns = [path("", include(router.urls))]
