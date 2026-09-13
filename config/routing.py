from django.urls import path

from apps.booking.consumers import BookingStreamConsumer
from apps.master.consumers import MasterStreamConsumer

websocket_urlpatterns = [
    path("ws/booking/", BookingStreamConsumer.as_asgi()),
    # Отдельный канал для сотрудников: другие права и другой контракт —
    # мастеру приходит сигнал об изменении, а не состояние чужой записи.
    path("ws/master/", MasterStreamConsumer.as_asgi()),
]
