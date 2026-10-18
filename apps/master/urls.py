from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.master.views import (
    LiveDraftListView,
    MasterBookingViewSet,
    MasterOilViewSet,
    MasterServiceCategoryViewSet,
    MasterServiceViewSet,
    MetricsView,
    WalkInViewSet,
)

app_name = "master"

router = DefaultRouter()
router.register("bookings", MasterBookingViewSet, basename="master-booking")
router.register("live-drafts", LiveDraftListView, basename="master-live-draft")
router.register(
    "service-categories", MasterServiceCategoryViewSet, basename="master-service-category"
)
router.register("services", MasterServiceViewSet, basename="master-service")
# Устарело: масла стали услугами, раздел отвечает поверх них.
router.register("oils", MasterOilViewSet, basename="master-oil")
router.register("walk-in", WalkInViewSet, basename="master-walk-in")

urlpatterns = [
    path("metrics/", MetricsView.as_view(), name="metrics"),
    path("", include(router.urls)),
]
