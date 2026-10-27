"""Обмен записями с «1С:Автосервисом»: выгрузка в заявки и правки из 1С."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.booking.constants import BookingStatus
from apps.booking.models import Booking, BookingStatusLog
from apps.booking.services import booking as booking_service
from apps.booking.services import draft as draft_service
from apps.catalog.models import Service, ServiceCategory
from apps.onec.models import BookingSync
from apps.onec.services import sync as sync_service

pytestmark = pytest.mark.django_db(transaction=True)

KEY = "k" * 40
ONEC_PHONE = "+79000000099"


@pytest.fixture(autouse=True)
def onec_settings(settings):
    settings.ONEC = {**settings.ONEC, "API_KEY": KEY, "USER_PHONE": ONEC_PHONE}


@pytest.fixture
def onec_user(db) -> User:
    return User.objects.create_master(phone=ONEC_PHONE, full_name="1С")


@pytest.fixture
def onec(api, onec_user):
    api.credentials(HTTP_AUTHORIZATION=f"OneC {KEY}")
    return api


def pending(api):
    return api.get(reverse("v1:onec:pending"))


def pending_ids(api):
    response = pending(api)
    assert response.status_code == 200, response.data
    return [row["id"] for row in response.data["bookings"]]


def ack(api, row, **extra):
    item = {"id": row["id"], "version": row["version"], **extra}
    return api.post(reverse("v1:onec:ack"), {"items": [item]}, format="json")


def changes(api, booking, *, request=None, order=None):
    item = {"id": str(booking.pk)}
    if request is not None:
        item["request"] = request
    if order is not None:
        item["order"] = order
    response = api.post(reverse("v1:onec:changes"), {"items": [item]}, format="json")
    assert response.status_code == 200, response.data
    return response.data["results"][0]


def exported(api, booking, *, request_version="v1"):
    """Запись выгружена и подтверждена 1С — как после первого обмена."""
    row = next(r for r in pending(api).data["bookings"] if r["id"] == str(booking.pk))
    response = ack(api, row, request_number="00000000001", request_version=request_version)
    assert response.status_code == 200
    return row


def local(booking, value):
    return sync_service.local(booking, value)


ORDER_REF = "5b0f6f3e-62f1-4a4b-9a55-0c0f3c4a2b11"


def order(**fields):
    return {
        "ref": ORDER_REF,
        "number": "АС-0001",
        "version": "o1",
        "state": "В работе",
        "posted": True,
        "deleted": False,
        "total": "4800.00",
        **fields,
    }


# ------------------------------------------------------------------ доступ
def test_disabled_without_key(api, onec_user, settings):
    settings.ONEC = {**settings.ONEC, "API_KEY": ""}
    api.credentials(HTTP_AUTHORIZATION=f"OneC {KEY}")
    response = api.get(reverse("v1:onec:ping"))
    assert response.status_code == 503
    assert response.data["error"]["code"] == "onec_disabled"


def test_short_key_does_not_enable_exchange(api, onec_user, settings):
    settings.ONEC = {**settings.ONEC, "API_KEY": "short"}
    api.credentials(HTTP_AUTHORIZATION="OneC short")
    assert api.get(reverse("v1:onec:ping")).status_code == 503


def test_wrong_key_is_401(api, onec_user):
    api.credentials(HTTP_AUTHORIZATION="OneC " + "x" * 40)
    response = api.get(reverse("v1:onec:ping"))
    assert response.status_code == 401
    assert response.data["error"]["code"] == "onec_bad_key"


def test_staff_jwt_cannot_pretend_to_be_1c(auth, master_user):
    """Иначе мастер подтвердил бы выгрузку за 1С и записи до неё не доехали."""
    response = auth(master_user).get(reverse("v1:onec:pending"))
    assert response.status_code in (401, 403)


def test_missing_1c_user_is_reported(api, db):
    api.credentials(HTTP_AUTHORIZATION=f"OneC {KEY}")
    response = api.get(reverse("v1:onec:ping"))
    assert response.status_code == 503
    assert response.data["error"]["code"] == "onec_user_missing"


def test_ping_names_the_acting_user(onec):
    response = onec.get(reverse("v1:onec:ping"))
    assert response.status_code == 200
    assert response.data["user"] == "1С"


# ------------------------------------------------------------------ выгрузка
def test_new_booking_is_exported_with_everything_for_the_request(onec, booking):
    row = pending(onec).data["bookings"][0]
    assert row["id"] == str(booking.pk)
    assert row["code"] == booking.code
    assert row["client"]["phone"] == booking.client_phone
    assert row["car"]["plate"] == "А123ВС77"
    assert row["services"][0]["title"] == booking.service_title
    assert row["services"][0]["price"] == "4800.00"
    # Время — местное время точки без пояса: в датах 1С пояса нет.
    assert row["start"] == local(booking, booking.start_at)
    assert "+" not in row["start"]


def test_acked_booking_is_not_exported_again_until_it_changes(onec, booking, master_user):
    exported(onec, booking)
    assert pending_ids(onec) == []

    booking_service.edit_by_master(master_user, booking.pk, comment="Позвонить за час")
    assert pending_ids(onec) == [str(booking.pk)]


def test_stale_ack_does_not_hide_a_newer_change(onec, booking, master_user):
    old = pending(onec).data["bookings"][0]
    booking_service.edit_by_master(master_user, booking.pk, comment="новое")
    new = pending(onec).data["bookings"][0]
    assert ack(onec, new).status_code == 200
    assert ack(onec, old).status_code == 200

    sync = BookingSync.objects.get(booking=booking)
    assert sync.exported_version.isoformat() == new["version"]


def test_booking_cancelled_before_export_never_reaches_1c(onec, booking, client_user):
    booking_service.cancel_by_client(client_user, booking.pk)
    assert pending_ids(onec) == []


def test_cancellation_after_export_reaches_1c(onec, booking, client_user):
    exported(onec, booking)
    booking_service.cancel_by_client(client_user, booking.pk)
    rows = pending(onec).data["bookings"]
    assert [r["status"] for r in rows] == [BookingStatus.CANCELLED_BY_CLIENT]


def test_old_bookings_are_not_exported(onec, booking):
    Booking.objects.filter(pk=booking.pk).update(
        start_at=timezone.now() - timedelta(days=5), end_at=timezone.now() - timedelta(days=5)
    )
    assert pending_ids(onec) == []


def test_batch_reports_more(onec, booking, settings):
    settings.ONEC = {**settings.ONEC, "BATCH_SIZE": 1}
    data = pending(onec).data
    assert len(data["bookings"]) == 1
    assert data["more"] is False


def test_1c_sees_only_points_of_its_user(onec, onec_user, booking, second_point):
    onec_user.service_points.set([second_point])
    assert pending_ids(onec) == []


def test_ack_error_is_kept_and_cleared(onec, booking):
    row = pending(onec).data["bookings"][0]
    ack(onec, row, error="Не найден цех")
    sync = BookingSync.objects.get(booking=booking)
    assert sync.last_error == "Не найден цех"
    assert pending_ids(onec) == []

    sync_service.resend(sync_service.actor(), booking.pk)
    row = pending(onec).data["bookings"][0]
    ack(onec, row, request_number="00000000007")
    sync.refresh_from_db()
    assert sync.last_error == ""
    assert sync.request_number == "00000000007"


def test_master_can_ask_to_resend(auth, master_user, booking, onec):
    exported(onec, booking)
    response = auth(master_user).post(reverse("v1:onec:resend", args=[booking.pk]))
    assert response.status_code == 200
    onec.force_authenticate(user=None)
    onec.credentials(HTTP_AUTHORIZATION=f"OneC {KEY}")
    assert pending_ids(onec) == [str(booking.pk)]


def test_linked_lists_exported_bookings_only(onec, booking, other_user, master_user):
    assert onec.get(reverse("v1:onec:linked")).data["ids"] == []
    exported(onec, booking)
    assert onec.get(reverse("v1:onec:linked")).data["ids"] == [str(booking.pk)]


def test_completed_booking_stays_linked_for_the_receipt(onec, booking, master_user):
    exported(onec, booking)
    booking_service.complete(master_user, booking.pk)
    assert onec.get(reverse("v1:onec:linked")).data["ids"] == [str(booking.pk)]


# ------------------------------------------------------------------ правки из 1С
def test_reschedule_in_1c_moves_the_booking(onec, booking, point):
    exported(onec, booking)
    new_start = booking.start_at + timedelta(minutes=point.slot_minutes)

    result = changes(onec, booking, request={"version": "v2", "start": local(booking, new_start)})

    assert result == {"id": str(booking.pk), "ok": True, "applied": ["rescheduled"]}
    booking.refresh_from_db()
    assert booking.start_at == new_start
    log = BookingStatusLog.objects.filter(booking=booking).latest("created_at")
    assert log.actor.full_name == "1С"


def test_request_rewritten_by_the_site_is_not_an_operator_edit(onec, booking, point, master_user):
    """Эхо: 1С переписала заявку из выгрузки и прислала её же — время не трогаем.

    Иначе перенос на сайте, сделанный между обменами, откатился бы
    временем из заявки, которую 1С ещё не успела обновить.
    """
    exported(onec, booking, request_version="v1")
    moved = booking.start_at + timedelta(minutes=point.slot_minutes)
    booking_service.edit_by_master(master_user, booking.pk, start_at=moved)

    stale = {"version": "v1", "start": local(booking, booking.start_at)}
    result = changes(onec, booking, request=stale)

    assert result["applied"] == []
    booking.refresh_from_db()
    assert booking.start_at == moved


def test_same_change_twice_is_applied_once(onec, booking, point):
    exported(onec, booking)
    new_start = booking.start_at + timedelta(minutes=point.slot_minutes)
    body = {"version": "v2", "start": local(booking, new_start)}
    assert changes(onec, booking, request=body)["applied"] == ["rescheduled"]
    assert changes(onec, booking, request=body)["applied"] == []


def test_rejected_change_sends_the_site_state_back(onec, booking):
    exported(onec, booking)
    past = booking.start_at - timedelta(days=3)

    result = changes(onec, booking, request={"version": "v2", "start": local(booking, past)})

    assert result["ok"] is False
    assert result["error"]["code"] == "slot_too_soon"
    booking.refresh_from_db()
    assert booking.start_at != past
    assert pending_ids(onec) == [str(booking.pk)]
    sync = BookingSync.objects.get(booking=booking)
    assert sync.last_error
    # Та же неудачная правка в следующем обмене не повторяется.
    assert changes(onec, booking, request={"version": "v2", "start": local(booking, past)})["ok"]


def test_deleted_request_cancels_the_booking(onec, booking):
    exported(onec, booking)
    result = changes(onec, booking, request={"version": "v2", "deleted": True})
    assert result["applied"] == ["cancelled"]
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED_BY_MASTER
    assert "1С" in booking.cancel_reason


def test_posted_order_puts_booking_in_progress(onec, booking):
    exported(onec, booking)
    result = changes(onec, booking, order=order())
    assert result["applied"] == ["started"]
    booking.refresh_from_db()
    assert booking.status == BookingStatus.IN_PROGRESS
    sync = BookingSync.objects.get(booking=booking)
    assert sync.order_number == "АС-0001"
    assert str(sync.order_ref) == ORDER_REF


def test_unposted_order_changes_nothing(onec, booking):
    exported(onec, booking)
    assert changes(onec, booking, order=order(posted=False))["applied"] == []
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING


def test_paid_order_completes_with_its_total_and_keeps_the_receipt(onec, booking):
    exported(onec, booking)
    changes(onec, booking, order=order())

    result = changes(onec, booking, order=order(
        version="o2", state="Выполнен", total="5300.00", paid_total="5300.00",
        receipt_number="17", paid_at=local(booking, timezone.now()),
    ))

    assert result["applied"] == ["completed"]
    booking.refresh_from_db()
    assert booking.status == BookingStatus.COMPLETED
    assert booking.final_price == Decimal("5300.00")
    sync = BookingSync.objects.get(booking=booking)
    assert sync.receipt_number == "17"
    assert sync.paid_total == Decimal("5300.00")
    assert sync.paid_at is not None


def test_receipt_alone_closes_the_booking(onec, booking):
    exported(onec, booking)
    result = changes(onec, booking, order=order(receipt_number="18"))
    assert result["applied"] == ["completed"]


def test_payment_after_completion_on_site_is_stored_only(onec, booking, master_user):
    exported(onec, booking)
    booking_service.complete(master_user, booking.pk)
    result = changes(onec, booking, order=order(state="Закрыт", receipt_number="19"))
    assert result == {"id": str(booking.pk), "ok": True, "applied": []}
    assert BookingSync.objects.get(booking=booking).receipt_number == "19"


@pytest.fixture
def on_site_booking(client_user, point, category, free_slot):
    """Запись «подберите на месте» — без позиций, только категория."""
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_category(client_user, draft.pk, category.pk)
    draft_service.select_service(client_user, draft.pk, on_site=True)
    draft_service.select_slot(client_user, draft.pk, free_slot.start_at)
    return draft_service.confirm(client_user, draft.pk)


def test_on_site_booking_takes_the_service_from_order_lines(onec, on_site_booking, service):
    exported(onec, on_site_booking)
    result = changes(onec, on_site_booking, order=order(
        state="Выполнен", lines=[{"name": service.name.upper()}],
    ))
    assert result["applied"] == ["completed"]
    on_site_booking.refresh_from_db()
    assert [item.service_id for item in on_site_booking.items.all()] == [service.pk]


def test_on_site_booking_without_matching_service_is_rejected(onec, on_site_booking):
    exported(onec, on_site_booking)
    result = changes(onec, on_site_booking, order=order(
        state="Выполнен", lines=[{"name": "Диагностика подвески"}],
    ))
    assert result["ok"] is False
    assert result["error"]["code"] == "onec_service_not_found"
    on_site_booking.refresh_from_db()
    assert on_site_booking.status == BookingStatus.PENDING


def test_one_bad_item_does_not_roll_back_the_others(onec, booking, other_user):
    exported(onec, booking)
    missing = {"id": "00000000-0000-0000-0000-000000000000", "order": order()}
    ok = {"id": str(booking.pk), "order": order()}
    response = onec.post(reverse("v1:onec:changes"), {"items": [missing, ok]}, format="json")
    results = response.data["results"]
    assert [r["ok"] for r in results] == [False, True]
    booking.refresh_from_db()
    assert booking.status == BookingStatus.IN_PROGRESS


def test_service_lookup_ignores_other_points(onec, on_site_booking, second_point):
    other = ServiceCategory.objects.create(service_point=second_point, name="Мойка")
    Service.objects.create(category=other, name="Мойка кузова", price=Decimal("600"))
    exported(onec, on_site_booking)
    result = changes(onec, on_site_booking, order=order(
        state="Выполнен", lines=[{"name": "Мойка кузова"}],
    ))
    assert result["ok"] is False


# ------------------------------------------------------------------ панель мастера
def test_master_sees_1c_state_of_the_booking(auth, master_user, onec, booking):
    exported(onec, booking)
    changes(onec, booking, order=order(receipt_number="21"))

    api = auth(master_user)
    body = api.get(reverse("v1:master:master-booking-detail", args=[booking.pk])).json()

    assert body["onec"]["request_number"] == "00000000001"
    assert body["onec"]["order_number"] == "АС-0001"
    assert body["onec"]["receipt_number"] == "21"


def test_booking_never_sent_to_1c_has_no_1c_state(auth, master_user, booking):
    url = reverse("v1:master:master-booking-detail", args=[booking.pk])
    assert auth(master_user).get(url).json()["onec"] is None
