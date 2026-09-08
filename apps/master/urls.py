from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.master.views import LiveDraftListView, MasterBookingViewSet, MetricsView

app_name = "master"

router = DefaultRouter()
router.register("bookings", MasterBookingViewSet, basename="master-booking")
router.register("live-drafts", LiveDraftListView, basename="master-live-draft")

urlpatterns = [
    path("metrics/", MetricsView.as_view(), name="metrics"),
    path("", include(router.urls)),
]
