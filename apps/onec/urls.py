from django.urls import path

from apps.onec.views import (
    OneCAckView,
    OneCChangesView,
    OneCLinkedView,
    OneCPendingView,
    OneCPingView,
    OneCResendView,
)
from apps.onec.workplace_views import (
    WorkplaceEventView,
    WorkplaceOrderView,
    WorkplacePrepareView,
    WorkplaceQuoteView,
)

app_name = "onec"

urlpatterns = [
    path(
        "workplace/bookings/<uuid:booking_id>/quote/",
        WorkplaceQuoteView.as_view(),
        name="workplace-quote",
    ),
    path(
        "workplace/bookings/<uuid:booking_id>/order/",
        WorkplaceOrderView.as_view(),
        name="workplace-order",
    ),
    path(
        "workplace/bookings/<uuid:booking_id>/prepare/",
        WorkplacePrepareView.as_view(),
        name="workplace-prepare",
    ),
    path(
        "workplace/bookings/<uuid:booking_id>/event/",
        WorkplaceEventView.as_view(),
        name="workplace-event",
    ),
    path("ping/", OneCPingView.as_view(), name="ping"),
    path("bookings/pending/", OneCPendingView.as_view(), name="pending"),
    path("bookings/ack/", OneCAckView.as_view(), name="ack"),
    path("bookings/linked/", OneCLinkedView.as_view(), name="linked"),
    path("bookings/changes/", OneCChangesView.as_view(), name="changes"),
    path("bookings/<uuid:booking_id>/resend/", OneCResendView.as_view(), name="resend"),
]
