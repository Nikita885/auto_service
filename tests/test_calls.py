"""Звонки клиентам: очередь «Кому позвонить», отметка звонка, журнал.

Очередь вычисляется на лету, поэтому тесты проверяют правила, а не
таблицу: какая причина появляется, когда снимается, в каком порядке идёт
и кто её видит.
"""

from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal

import pytest
from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from rest_framework_simplejwt.tokens import AccessToken

from apps.booking import events
from apps.booking.constants import BookingStatus, CallReason
from apps.booking.models import Booking, BookingCall, generate_booking_code
from apps.booking.services import booking as booking_service
from apps.booking.services import calls as calls_service
from apps.booking.services import draft as draft_service
from apps.catalog.models import ServicePoint
from apps.common.ws_auth import JWTAuthMiddleware
from config.routing import websocket_urlpatterns

pytestmark = pytest.mark.django_db(transaction=True)

QUEUE_URL = reverse("v1:master:calls")


def calls_url(booking):
    return reverse("v1:master:master-booking-calls", args=[booking.pk])


def queue(api, **params):
    response = api.get(QUEUE_URL, params)
    assert response.status_code == 200, response.content
    return response.json()


def noon(point):
    """Полдень сегодня по времени точки: «опоздал» и «не приехал» считаются
    в пределах суток, и тест не должен зависеть от того, что прогон
    случился около полуночи."""
    return timezone.now().astimezone(point.tz).replace(hour=12, minute=0, second=0, microsecond=0)


def make_booking(user, point, start_at, *, status=BookingStatus.PENDING, on_site=False):
    """Запись напрямую через ORM: время и статус нужны произвольные."""
    return Booking.objects.create(
        code=generate_booking_code(),
        user=user,
        service_point=point,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
        status=status,
        client_name=user.full_name,
        client_phone=user.phone,
        category_title="Замена масла",
        service_title="Подберём на месте" if on_site else "Shell",
        service_on_site=on_site,
        oil_title="Shell",
        oil_price=Decimal(0),
        work_price=Decimal(0),
        total_price=Decimal(0),
    )


@pytest.fixture
def on_site_booking(client_user, point, category, free_slot):
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_category(client_user, draft.pk, category.pk)
    draft_service.select_service(client_user, draft.pk, on_site=True)
    draft_service.select_slot(client_user, draft.pk, free_slot.start_at)
    return draft_service.confirm(client_user, draft.pk)


# ----------------------------------------------------------------- очередь
def test_on_site_booking_is_first_with_category_hint(auth, master_user, on_site_booking):
    rows = queue(auth(master_user))

    assert [row["booking_code"] for row in rows] == [on_site_booking.code]
    assert rows[0]["reason"] == CallReason.ON_SITE
    assert rows[0]["hint"] == "Подобрать услугу: Замена масла"
    assert rows[0]["client_phone"] == on_site_booking.client_phone
    assert rows[0]["attempts"] == 0 and rows[0]["last_call"] is None


def test_one_row_per_booking_by_the_most_urgent_reason(auth, master_user, on_site_booking):
    """Запись на завтра без услуги — это и «на завтра», и «подобрать»: в
    очереди одна строка, по самой срочной причине."""
    rows = queue(auth(master_user))

    assert len(rows) == 1
    assert rows[0]["reason"] == CallReason.ON_SITE


def test_order_follows_the_customer_priority(auth, master_user, client_user, other_user, point):
    with freeze_time(noon(point)):
        now = timezone.now()
        late = make_booking(client_user, point, now - timedelta(minutes=20))
        on_site = make_booking(other_user, point, now + timedelta(hours=3), on_site=True)
        rows = queue(auth(master_user))

    assert [row["booking_code"] for row in rows] == [on_site.code, late.code]
    assert [row["reason"] for row in rows] == [CallReason.ON_SITE, CallReason.LATE]


def test_late_starts_after_the_threshold(auth, master_user, client_user, point, settings):
    start = timezone.now().replace(second=0, microsecond=0) + timedelta(hours=1)
    booking = make_booking(client_user, point, start)
    threshold = settings.BOOKING["CALL_LATE_MINUTES"]
    api = auth(master_user)

    with freeze_time(start + timedelta(minutes=threshold - 1)):
        assert all(row["reason"] != CallReason.LATE for row in queue(api))
    with freeze_time(start + timedelta(minutes=threshold + 1)):
        rows = queue(api)
    assert (rows[0]["booking_code"], rows[0]["reason"]) == (booking.code, CallReason.LATE)


def test_tomorrow_booking_is_listed_until_reached(auth, master_user, booking):
    api = auth(master_user)
    assert queue(api)[0]["reason"] == CallReason.TOMORROW

    api.post(calls_url(booking), {"outcome": "reached", "reason": "tomorrow"}, format="json")

    assert queue(api) == []


def test_no_answer_keeps_the_row_and_counts_attempts(auth, master_user, booking):
    api = auth(master_user)
    api.post(calls_url(booking), {"outcome": "no_answer", "note": "занято"}, format="json")

    row = queue(api)[0]

    assert row["attempts"] == 1
    assert row["last_call"]["outcome"] == "no_answer"
    assert row["last_call"]["note"] == "занято"


def test_callback_hides_the_row_until_its_time(auth, master_user, booking):
    api = auth(master_user)
    when = timezone.now() + timedelta(hours=2)
    created = api.post(
        calls_url(booking),
        {"outcome": "callback", "callback_at": when.isoformat(), "note": "после обеда"},
        format="json",
    )
    assert created.status_code == 201, created.content

    assert queue(api) == []
    with freeze_time(when + timedelta(minutes=1)):
        rows = queue(api)
    assert rows[0]["reason"] == CallReason.CALLBACK
    assert rows[0]["hint"] == "после обеда"


def test_off_hours_booking_needs_a_confirmation_call(auth, master_user, client_user):
    point = ServicePoint.objects.create(
        name="Дневная",
        address="ул. Дневная, 1",
        opens_at=time(9, 0),
        closes_at=time(21, 0),
        workdays=[0, 1, 2, 3, 4, 5, 6],
        posts_count=1,
        timezone="Europe/Moscow",
    )
    start = timezone.now() + timedelta(days=2)
    booking = make_booking(client_user, point, start)
    # Запись пришла в 23:00 по времени точки — после закрытия.
    night = (timezone.now().astimezone(point.tz) - timedelta(days=1)).replace(hour=23, minute=0)
    Booking.objects.filter(pk=booking.pk).update(created_at=night)

    rows = queue(auth(master_user), service_point=str(point.pk))

    assert [(row["booking_code"], row["reason"]) for row in rows] == [
        (booking.code, CallReason.OFF_HOURS)
    ]


def test_no_show_today_asks_to_rebook(auth, master_user, client_user, point):
    with freeze_time(noon(point)):
        booking = make_booking(client_user, point, timezone.now() - timedelta(minutes=40))
        booking_service.mark_no_show(master_user, booking.pk)
        rows = queue(auth(master_user))

    assert [row["reason"] for row in rows] == [CallReason.NO_SHOW]


def test_completed_and_cancelled_bookings_are_not_called(auth, master_user, client_user, point):
    with freeze_time(noon(point)):
        now = timezone.now()
        make_booking(
            client_user, point, now - timedelta(minutes=30), status=BookingStatus.COMPLETED
        )
        make_booking(
            client_user,
            point,
            now - timedelta(minutes=60),
            status=BookingStatus.CANCELLED_BY_MASTER,
        )
        assert queue(auth(master_user)) == []


# -------------------------------------------------------- права и точки
def test_master_sees_only_his_points(auth, master_user, client_user, point, second_point, booking):
    master_user.service_points.add(second_point)

    assert queue(auth(master_user)) == []
    refused = auth(master_user).get(QUEUE_URL, {"service_point": str(point.pk)})
    assert refused.status_code == 403


def test_master_of_another_point_cannot_log_a_call(auth, master_user, second_point, booking):
    master_user.service_points.add(second_point)

    response = auth(master_user).post(calls_url(booking), {"outcome": "reached"}, format="json")

    assert response.status_code == 403
    assert not BookingCall.objects.exists()


def test_client_has_no_access_to_calls(auth, client_user, booking):
    api = auth(client_user)

    assert api.get(QUEUE_URL).status_code == 403
    assert api.post(calls_url(booking), {"outcome": "reached"}, format="json").status_code == 403


# ------------------------------------------------------------- отметка
@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"outcome": "callback"}, "call_callback_time_required"),
        (
            {"outcome": "callback", "callback_at": "2020-01-01T10:00:00+03:00"},
            "call_callback_time_in_past",
        ),
        (
            {"outcome": "reached", "callback_at": "2099-01-01T10:00:00+03:00"},
            "call_callback_time_unexpected",
        ),
    ],
)
def test_callback_time_rules(auth, master_user, booking, body, code):
    response = auth(master_user).post(calls_url(booking), body, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


def test_double_tap_is_one_call(auth, master_user, booking):
    api = auth(master_user)
    first = api.post(calls_url(booking), {"outcome": "no_answer"}, format="json").json()
    second = api.post(calls_url(booking), {"outcome": "no_answer"}, format="json").json()

    assert first["id"] == second["id"]
    assert BookingCall.objects.count() == 1


def test_journal_by_booking_and_by_client(auth, master_user, booking, client_user):
    api = auth(master_user)
    api.post(calls_url(booking), {"outcome": "no_answer"}, format="json")
    with freeze_time(timezone.now() + timedelta(minutes=5)):
        api.post(calls_url(booking), {"outcome": "reached", "note": "приедет"}, format="json")

    by_booking = api.get(calls_url(booking)).json()
    by_client = api.get(reverse("v1:master:client-calls", args=[client_user.pk])).json()

    assert [call["outcome"] for call in by_booking] == ["reached", "no_answer"]  # новые сверху
    assert by_booking[0]["actor"] == master_user.display_name
    assert [call["id"] for call in by_client] == [call["id"] for call in by_booking]


def test_call_from_client_card_without_booking(auth, master_user, client_user, point):
    """Из карточки клиента звонят и без записи: «перезвонить» встаёт в
    очередь, когда подходит время."""
    api = auth(master_user)
    when = timezone.now() + timedelta(hours=1)
    response = api.post(
        reverse("v1:master:client-calls", args=[client_user.pk]),
        {"outcome": "callback", "callback_at": when.isoformat(), "service_point": str(point.pk)},
        format="json",
    )
    assert response.status_code == 201, response.content

    with freeze_time(when + timedelta(minutes=1)):
        rows = queue(api)
    assert [(row["reason"], row["booking"], row["client"]) for row in rows] == [
        (CallReason.CALLBACK, None, str(client_user.pk))
    ]


def test_service_layer_rejects_staff_as_client(master_user, point):
    from apps.common.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        calls_service.log_call(
            master_user, client_id=master_user.pk, point_id=point.pk, outcome="reached"
        )


# ---------------------------------------------------------- реальное время
application = JWTAuthMiddleware(URLRouter(websocket_urlpatterns))


@pytest.mark.asyncio
async def test_call_reaches_every_master_of_the_point(master_user, booking):
    token = str(AccessToken.for_user(master_user))
    communicator = WebsocketCommunicator(application, f"/ws/master/?token={token}")
    connected, _ = await communicator.connect()
    assert connected
    await communicator.receive_json_from(timeout=3)  # master.ready

    await sync_to_async(calls_service.log_call)(
        master_user, booking_id=booking.pk, outcome="reached", note="личное"
    )
    message = await communicator.receive_json_from(timeout=3)

    assert message["event"] == events.CALL_LOGGED
    assert message["payload"]["booking_id"] == str(booking.pk)
    # В канал уходит только сигнал: ни телефона, ни заметки.
    assert "личное" not in str(message) and booking.client_phone not in str(message)
    await communicator.disconnect()
