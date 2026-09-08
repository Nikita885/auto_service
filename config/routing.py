from django.urls import path

from apps.booking.consumers import BookingStreamConsumer

websocket_urlpatterns = [
    path("ws/booking/", BookingStreamConsumer.as_asgi()),
]
