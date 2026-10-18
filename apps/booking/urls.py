from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.booking.views import (
    BookingDraftViewSet,
    BookingViewSet,
    PointCategoriesView,
    PointOilsView,
    PointServicesView,
    PointSlotsView,
)

app_name = "booking"

router = DefaultRouter()
router.register("bookings/drafts", BookingDraftViewSet, basename="booking-draft")
router.register("bookings", BookingViewSet, basename="booking")

urlpatterns = [
    path(
        "service-points/<uuid:point_id>/categories/",
        PointCategoriesView.as_view(),
        name="point-categories",
    ),
    path(
        "service-points/<uuid:point_id>/services/",
        PointServicesView.as_view(),
        name="point-services",
    ),
    # Устарело: масла стали услугами, ручка отвечает из тех же услуг.
    path(
        "service-points/<uuid:point_id>/oils/",
        PointOilsView.as_view(),
        name="point-oils",
    ),
    path(
        "service-points/<uuid:point_id>/slots/",
        PointSlotsView.as_view(),
        name="point-slots",
    ),
    path("", include(router.urls)),
]
