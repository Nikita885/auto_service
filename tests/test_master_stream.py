"""WebSocket-канал сотрудника: доступ и сигналы об изменениях.

Тесты асинхронные: `WebsocketCommunicator` живёт в цикле событий, и
загнать его в синхронный тест мостом `async_to_sync` не выходит — цикл
отменяет ожидание. Обращения к базе внутри теста, наоборот, синхронные,
поэтому идут через `sync_to_async`.
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.booking import events
from apps.booking.services import booking as booking_service
from apps.booking.services import draft as draft_service
from apps.common.ws_auth import JWTAuthMiddleware
from config.routing import websocket_urlpatterns

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

application = JWTAuthMiddleware(URLRouter(websocket_urlpatterns))


@pytest.fixture
def admin_user(db) -> User:
    return User.objects.create_superuser(phone="+79000000000", password="admin12345")


async def connect(user):
    token = str(AccessToken.for_user(user))
    communicator = WebsocketCommunicator(application, f"/ws/master/?token={token}")
    connected, _ = await communicator.connect()
    return communicator, connected


async def hello(communicator):
    """Первое сообщение канала — список точек, за которыми он следит."""
    return await communicator.receive_json_from(timeout=3)


# ---------------------------------------------------------------- доступ
async def test_client_is_not_allowed_into_master_stream(client_user):
    communicator, connected = await connect(client_user)

    assert connected is False
    await communicator.disconnect()


async def test_master_connects_and_gets_his_points(master_user, point, second_point):
    """Мастер без привязки к точкам следит за всеми — как и в REST."""
    communicator, connected = await connect(master_user)

    assert connected is True
    message = await hello(communicator)
    assert message["event"] == "master.ready"
    assert set(message["payload"]["service_points"]) == {str(point.pk), str(second_point.pk)}
    await communicator.disconnect()


async def test_master_with_point_sees_only_his_point(master_user, point, second_point):
    await sync_to_async(master_user.service_points.add)(point)

    communicator, _ = await connect(master_user)
    message = await hello(communicator)

    assert message["payload"]["service_points"] == [str(point.pk)]
    await communicator.disconnect()


async def test_admin_sees_every_point(admin_user, point, second_point):
    communicator, _ = await connect(admin_user)
    message = await hello(communicator)

    assert len(message["payload"]["service_points"]) == 2
    await communicator.disconnect()


# --------------------------------------------------------------- сигналы
async def test_new_booking_reaches_the_master(master_user, client_user, ready_draft, point):
    communicator, _ = await connect(master_user)
    await hello(communicator)

    booking = await sync_to_async(draft_service.confirm)(client_user, ready_draft.pk)

    # Подтверждение шлёт два события: закрытие черновика и создание записи.
    seen = [await communicator.receive_json_from(timeout=3) for _ in range(2)]
    created = next(msg for msg in seen if msg["event"] == events.BOOKING_CREATED)

    assert created["payload"]["booking_id"] == str(booking.id)
    assert created["payload"]["code"] == booking.code
    assert created["payload"]["status"] == booking.status
    await communicator.disconnect()


async def test_cancel_by_client_reaches_the_master(master_user, client_user, ready_draft):
    booking = await sync_to_async(draft_service.confirm)(client_user, ready_draft.pk)

    communicator, _ = await connect(master_user)
    await hello(communicator)

    await sync_to_async(booking_service.cancel_by_client)(
        client_user, booking.pk, reason="Передумал"
    )
    message = await communicator.receive_json_from(timeout=3)

    assert message["event"] == events.BOOKING_CANCELLED
    assert message["payload"]["booking_id"] == str(booking.id)
    await communicator.disconnect()


async def test_master_of_another_point_hears_nothing(
    master_user, client_user, ready_draft, second_point
):
    """Чужая точка — чужие записи: сигнал туда не уходит."""
    await sync_to_async(master_user.service_points.add)(second_point)

    communicator, _ = await connect(master_user)
    await hello(communicator)

    await sync_to_async(draft_service.confirm)(client_user, ready_draft.pk)

    assert await communicator.receive_nothing(timeout=0.5) is True
    await communicator.disconnect()


async def test_draft_without_point_is_not_broadcast(master_user, client_user):
    """Пока адрес не выбран, черновик не относится ни к одной точке."""
    communicator, _ = await connect(master_user)
    await hello(communicator)

    await sync_to_async(draft_service.start_draft)(client_user)

    assert await communicator.receive_nothing(timeout=0.5) is True
    await communicator.disconnect()


async def test_draft_with_point_is_broadcast(master_user, client_user, point, stock):
    """А как только адрес выбран — мастер видит, что человек записывается."""
    communicator, _ = await connect(master_user)
    await hello(communicator)

    draft = await sync_to_async(draft_service.start_draft)(client_user)
    await sync_to_async(draft_service.select_point)(client_user, draft.pk, point.pk)
    message = await communicator.receive_json_from(timeout=3)

    assert message["event"] == events.DRAFT_UPDATED
    assert message["payload"]["draft_id"] == str(draft.pk)
    assert message["payload"]["is_open"] is True
    await communicator.disconnect()


async def test_signal_carries_no_personal_data(master_user, client_user, ready_draft):
    """В канал уходит только сигнал: имя и телефон клиента забираются по REST,
    где права проверяются на каждый запрос."""
    communicator, _ = await connect(master_user)
    await hello(communicator)

    await sync_to_async(draft_service.confirm)(client_user, ready_draft.pk)
    payloads = [(await communicator.receive_json_from(timeout=3))["payload"] for _ in range(2)]

    for payload in payloads:
        assert "client_name" not in payload
        assert "client_phone" not in payload
    await communicator.disconnect()


async def test_client_channel_still_gets_full_state(client_user, ready_draft):
    """Клиентский канал не задет: ему по-прежнему приходит полное состояние."""
    layer = get_channel_layer()
    await layer.group_add(events.user_group(client_user.id), "test-client-channel")

    await sync_to_async(draft_service.cancel_draft)(client_user, ready_draft.pk)
    message = await layer.receive("test-client-channel")

    assert message["event"] == events.DRAFT_CLOSED
    assert message["payload"]["id"] == str(ready_draft.pk)
    assert message["payload"]["service_point"]["id"]
