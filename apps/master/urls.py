from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.master.views import LiveDraftListView, MasterBookingViewSet

app_name = "master"

router = DefaultRouter()
router.register("bookings", MasterBookingViewSet, basename="master-booking")
router.register("live-drafts", LiveDraftListView, basename="master-live-draft")

urlpatterns = [path("", include(router.urls))]
