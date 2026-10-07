"""Перенос записи клиентом: другое время той же точки.

Правило переноса — то же, что у отмены: пока можно отменить, можно и
перенести. Новое время проверяется как при записи.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from apps.booking.constants import BookingStatus
from apps.booking.models import Booking, BookingStatusLog
from apps.booking.services import draft as draft_service
from apps.booking.services.slots import build_slots

pytestmark = pytest.mark.django_db(transaction=True)


def url(booking):
    return reverse("v1:booking:booking-reschedule", args=[booking.pk])


def move(api, booking, start_at):
    return api.post(url(booking), {"start_at": start_at.isoformat()}, format="json")


def other_slot(point, booking, settings):
    """Свободный слот той же точки, не равный времени записи и далёкий от дедлайнов."""
    margin = timedelta(minutes=settings.BOOKING["CANCEL_DEADLINE_MINUTES"] + 120)
    day = booking.start_at.astimezone(point.tz).date()
    for offset in (0, 1):
        for slot in build_slots(point, day + timedelta(days=offset)):
            if slot.start_at != booking.start_at and slot.start_at - timezone.now() >= margin:
                return slot
    raise AssertionError("нет второго свободного слота")


def test_client_moves_booking(auth, client_user, booking, point, settings):
    target = other_slot(point, booking, settings)
    Booking.objects.filter(pk=booking.pk).update(reminder_sent_at=timezone.now())

    resp = move(auth(client_user), booking, target.start_at)

    assert resp.status_code == 200, resp.content
    booking.refresh_from_db()
    assert booking.start_at == target.start_at
    assert booking.end_at == target.end_at
    assert booking.status == BookingStatus.PENDING
    # Напоминание уйдёт заново — к новому времени.
    assert booking.reminder_sent_at is None
    log = BookingStatusLog.objects.filter(booking=booking).first()
    assert log.comment.startswith("Перенесена клиентом")
    assert resp.json()["can_reschedule"] is True


def test_old_time_is_freed_and_new_is_taken(auth, client_user, booking, point, settings):
    """Пост один: после переноса старое время свободно, новое занято."""
    old = booking.start_at
    target = other_slot(point, booking, settings)
    move(auth(client_user), booking, target.start_at)

    day = old.astimezone(point.tz).date()
    free = {s.start_at for s in build_slots(point, day)}
    assert old in free
    target_day = target.start_at.astimezone(point.tz).date()
    assert target.start_at not in {s.start_at for s in build_slots(point, target_day)}


def test_taken_slot_is_refused(auth, client_user, other_user, booking, point, stock, settings):
    target = other_slot(point, booking, settings)
    stock.quantity = 5
    stock.save()
    draft = draft_service.start_draft(other_user)
    draft_service.select_point(other_user, draft.pk, point.pk)
    draft_service.select_oil(other_user, draft.pk, stock.oil_id)
    draft_service.select_slot(other_user, draft.pk, target.start_at)

    resp = move(auth(client_user), booking, target.start_at)

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "slot_taken"
    booking.refresh_from_db()
    assert booking.start_at != target.start_at


def test_same_time_is_refused(auth, client_user, booking):
    resp = move(auth(client_user), booking, booking.start_at)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "reschedule_same_time"


def test_too_late_to_move(auth, client_user, booking, point, settings):
    target = other_slot(point, booking, settings)
    deadline = booking.start_at - timedelta(minutes=settings.BOOKING["CANCEL_DEADLINE_MINUTES"])
    with freeze_time(deadline + timedelta(minutes=1)):
        resp = move(auth(client_user), booking, target.start_at)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "reschedule_deadline_passed"


def test_cancelled_booking_cannot_move(auth, client_user, booking, point, settings):
    target = other_slot(point, booking, settings)
    cancel_url = reverse("v1:booking:booking-cancel", args=[booking.pk])
    auth(client_user).post(cancel_url, {}, format="json")

    resp = move(auth(client_user), booking, target.start_at)

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "reschedule_deadline_passed"


def test_slot_outside_schedule_is_refused(auth, client_user, booking):
    odd = booking.start_at + timedelta(minutes=7)
    resp = move(auth(client_user), booking, odd)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "slot_not_in_schedule"


def test_foreign_booking_is_not_found(auth, other_user, booking, point, settings):
    target = other_slot(point, booking, settings)
    resp = move(auth(other_user), booking, target.start_at)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "booking_not_found"


def test_own_other_booking_at_that_time(
    auth, client_user, booking, point, second_point, oil, settings
):
    """Своя запись на другой точке в то же время — дубль, а не перенос."""
    from apps.catalog.models import OilStock

    target = other_slot(point, booking, settings)
    OilStock.objects.create(service_point=second_point, oil=oil, quantity=3)
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, second_point.pk)
    draft_service.select_oil(client_user, draft.pk, oil.pk)
    draft_service.select_slot(client_user, draft.pk, target.start_at)
    draft_service.confirm(client_user, draft.pk)

    resp = move(auth(client_user), booking, target.start_at)

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "duplicate_booking"
