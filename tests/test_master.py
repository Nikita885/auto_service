"""Панель мастера: доступ, отмена с уведомлением, статусы."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from freezegun import freeze_time

from apps.booking.constants import BookingStatus
from apps.booking.models import Booking, BookingStatusLog
from apps.booking.services import draft as draft_service
from apps.catalog.models import OilStock
from apps.notifications.models import Notification, NotificationKind

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def booking(client_user, point, stock, free_slot) -> Booking:
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_oil(client_user, draft.pk, stock.oil_id)
    draft_service.select_slot(client_user, draft.pk, free_slot.start_at)
    return draft_service.confirm(client_user, draft.pk)


def master_url(name, *args):
    return reverse(f"v1:master:master-booking-{name}", args=args)


# ---------------------------------------------------------------- доступ
def test_client_cannot_open_master_api(auth, client_user, booking):
    response = auth(client_user).get(master_url("list"))

    assert response.status_code == 403


def test_master_sees_client_name_and_oil(auth, master_user, booking):
    response = auth(master_user).get(master_url("list"))

    assert response.status_code == 200
    row = response.data["results"][0]
    assert row["client_name"] == "Иван Тестов"
    assert row["client_phone"] == "+79001112233"
    assert row["oil_title"] == booking.oil_title
    assert row["car_plate"] == "А123ВС77"
    assert row["code"] == booking.code


def test_master_is_limited_to_own_points(auth, master_user, booking, second_point):
    master_user.service_points.add(second_point)

    listed = auth(master_user).get(master_url("list"))
    assert listed.data["results"] == []

    denied = auth(master_user).post(
        master_url("cancel", booking.pk), {"reason": "Нет мастера"}, format="json"
    )
    assert denied.status_code == 403
    assert denied.data["error"]["code"] == "point_not_allowed"


def test_search_finds_booking_by_plate(auth, master_user, booking):
    response = auth(master_user).get(master_url("list") + "?search=А123ВС77")

    assert len(response.data["results"]) == 1


# ---------------------------------------------------------------- отмена
def test_master_cancel_notifies_client(auth, master_user, booking):
    response = auth(master_user).post(
        master_url("cancel", booking.pk),
        {"reason": "Сломался подъёмник"},
        format="json",
    )

    assert response.status_code == 200

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED_BY_MASTER
    assert booking.cancel_reason == "Сломался подъёмник"
    assert booking.cancelled_by == master_user
    assert booking.cancelled_at is not None

    notification = Notification.objects.get(
        kind=NotificationKind.BOOKING_CANCELLED_BY_MASTER
    )
    assert notification.phone == booking.client_phone
    assert "Сломался подъёмник" in notification.text

    assert BookingStatusLog.objects.filter(
        booking=booking, to_status=BookingStatus.CANCELLED_BY_MASTER, actor=master_user
    ).exists()


def test_cancel_reason_is_required(auth, master_user, booking):
    response = auth(master_user).post(
        master_url("cancel", booking.pk), {"reason": ""}, format="json"
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"


def test_cancelled_slot_becomes_free_again(auth, master_user, booking, point, free_slot):
    from apps.booking.services.slots import build_slots

    day = free_slot.start_at.astimezone(point.tz).date()
    assert not [s for s in build_slots(point, day) if s.start_at == free_slot.start_at]

    auth(master_user).post(
        master_url("cancel", booking.pk), {"reason": "Форс-мажор"}, format="json"
    )

    assert [s for s in build_slots(point, day) if s.start_at == free_slot.start_at]


# ---------------------------------------------------------------- статусы
def test_work_cycle_writes_off_stock(auth, master_user, booking, stock):
    api = auth(master_user)

    assert api.post(master_url("start", booking.pk)).status_code == 200
    booking.refresh_from_db()
    assert booking.status == BookingStatus.IN_PROGRESS
    assert booking.master == master_user

    assert api.post(master_url("complete", booking.pk)).status_code == 200
    booking.refresh_from_db()
    assert booking.status == BookingStatus.COMPLETED

    stock.refresh_from_db()
    assert stock.quantity == 0  # канистра списана ровно один раз

    assert Notification.objects.filter(
        kind=NotificationKind.BOOKING_COMPLETED
    ).exists()


def test_invalid_transition_is_rejected(auth, master_user, booking):
    api = auth(master_user)
    api.post(master_url("start", booking.pk))
    api.post(master_url("complete", booking.pk))

    response = api.post(master_url("start", booking.pk))

    assert response.status_code == 409
    assert response.data["error"]["code"] == "booking_final"


def test_no_show(auth, master_user, booking):
    response = auth(master_user).post(
        master_url("no-show", booking.pk), {"reason": "Не приехал"}, format="json"
    )

    assert response.status_code == 200
    booking.refresh_from_db()
    assert booking.status == BookingStatus.NO_SHOW


def test_day_summary(auth, master_user, booking, point):
    day = booking.local_start().date().isoformat()

    response = auth(master_user).get(
        master_url("summary") + f"?date={day}&service_point={point.pk}"
    )

    assert response.status_code == 200
    assert response.data["total"] == 1
    assert response.data["pending"] == 1


def test_live_drafts_visible_to_master(auth, master_user, client_user, point, stock):
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_oil(client_user, draft.pk, stock.oil_id)

    response = auth(master_user).get(reverse("v1:master:master-live-draft-list"))

    assert response.status_code == 200
    assert response.data[0]["client_phone"] == client_user.phone
    assert response.data[0]["oil_title"] == str(stock.oil)


# --------------------------------------------------------- отмена клиентом
def test_client_can_cancel_own_booking(auth, client_user, booking):
    response = auth(client_user).post(
        reverse("v1:booking:booking-cancel", args=[booking.pk]),
        {"reason": "Передумал"},
        format="json",
    )

    assert response.status_code == 200
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED_BY_CLIENT
    assert booking.cancelled_by == client_user


def test_client_cannot_cancel_too_late(auth, client_user, booking, settings):
    deadline = settings.BOOKING["CANCEL_DEADLINE_MINUTES"]

    with freeze_time(booking.start_at - timedelta(minutes=deadline - 1)):
        response = auth(client_user).post(
            reverse("v1:booking:booking-cancel", args=[booking.pk]), {}, format="json"
        )

    assert response.status_code == 409
    assert response.data["error"]["code"] == "cancel_deadline_passed"


def test_client_cannot_cancel_foreign_booking(auth, other_user, booking):
    response = auth(other_user).post(
        reverse("v1:booking:booking-cancel", args=[booking.pk]), {}, format="json"
    )

    assert response.status_code == 404


def test_client_sees_only_own_bookings(auth, other_user, booking):
    response = auth(other_user).get(reverse("v1:booking:booking-list"))

    assert response.data["results"] == []


def test_stock_is_not_written_off_twice(auth, master_user, booking, stock):
    api = auth(master_user)
    api.post(master_url("start", booking.pk))
    api.post(master_url("complete", booking.pk))
    api.post(master_url("complete", booking.pk))  # повтор — уже финальный статус

    stock.refresh_from_db()
    assert stock.quantity == 0


def test_reminder_is_sent_once(booking, settings):
    from apps.booking.tasks import send_booking_reminders

    lead = settings.BOOKING["REMINDER_LEAD_MINUTES"]
    with freeze_time(booking.start_at - timedelta(minutes=lead - 1)):
        assert send_booking_reminders() == 1
        assert send_booking_reminders() == 0

    assert (
        Notification.objects.filter(kind=NotificationKind.BOOKING_REMINDER).count() == 1
    )


def test_completed_booking_frees_the_slot_for_others(auth, master_user, booking, point, free_slot):
    """Выполненная запись перестаёт занимать пост."""
    from apps.booking.services.slots import build_slots

    OilStock.objects.filter(service_point=point).update(quantity=5)
    api = auth(master_user)
    api.post(master_url("start", booking.pk))
    api.post(master_url("complete", booking.pk))

    day = free_slot.start_at.astimezone(point.tz).date()
    assert [s for s in build_slots(point, day) if s.start_at == free_slot.start_at]


def test_timezone_of_local_time_field(auth, master_user, booking):
    response = auth(master_user).get(master_url("list"))

    expected = booking.start_at.astimezone(booking.service_point.tz)
    assert response.data["results"][0]["local_time"] == expected.strftime("%d.%m.%Y %H:%M")


def test_unauthenticated_master_api(api):
    assert api.get(master_url("list")).status_code == 401


def test_status_history_visible_in_detail(auth, master_user, booking):
    api = auth(master_user)
    api.post(master_url("start", booking.pk))

    response = api.get(master_url("detail", booking.pk))

    assert response.status_code == 200
    statuses = [log["to_status"] for log in response.data["status_logs"]]
    assert BookingStatus.IN_PROGRESS in statuses
