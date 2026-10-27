from django.urls import path

from apps.onec.views import (
    OneCAckView,
    OneCChangesView,
    OneCLinkedView,
    OneCPendingView,
    OneCPingView,
    OneCResendView,
)

app_name = "onec"

urlpatterns = [
    path("ping/", OneCPingView.as_view(), name="ping"),
    path("bookings/pending/", OneCPendingView.as_view(), name="pending"),
    path("bookings/ack/", OneCAckView.as_view(), name="ack"),
    path("bookings/linked/", OneCLinkedView.as_view(), name="linked"),
    path("bookings/changes/", OneCChangesView.as_view(), name="changes"),
    path("bookings/<uuid:booking_id>/resend/", OneCResendView.as_view(), name="resend"),
]
