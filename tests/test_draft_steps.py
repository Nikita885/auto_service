"""Переход на пройденный шаг записи и «подберите масло на месте».

Вперёд шаги идут по порядку, назад — на любой пройденный, без потери
таймера. «Подберите на месте» — запись без масла, которая стоит в очереди
звонков у мастера, пока он не выберет масло вместе с клиентом.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from freezegun import freeze_time

from apps.booking.constants import BookingStatus, DraftStep
from apps.booking.models import Booking, BookingDraft
from apps.booking.services import draft as draft_service
from apps.booking.services.booking import ON_SITE_OIL_TITLE
from apps.catalog.models import Oil, OilStock, OilType
from apps.master.metrics import _funnel
from apps.notifications.models import Notification, NotificationKind

pytestmark = pytest.mark.django_db(transaction=True)


def step(api, draft_id, name, body=None):
    url = reverse(f"v1:booking:booking-draft-{name}", args=[draft_id])
    return api.post(url, body or {}, format="json")


def master_url(name, *args):
    return reverse(f"v1:master:master-booking-{name}", args=args)


@pytest.fixture
def second_oil(point):
    oil = Oil.objects.create(
        brand="Mobil", name="Super 3000", viscosity="5W-40", oil_type=OilType.SYNTHETIC,
        volume_liters=Decimal("4.0"), price=Decimal("3500"), work_price=Decimal("800"),
    )
    OilStock.objects.create(service_point=point, oil=oil, quantity=3)
    return oil


@pytest.fixture
def on_site_booking(client_user, point, free_slot):
    """Запись «подберите на месте»: масла нет, цены нулевые."""
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_oil(client_user, draft.pk, on_site=True)
    draft_service.select_slot(client_user, draft.pk, free_slot.start_at)
    return draft_service.confirm(client_user, draft.pk)


# ------------------------------------------------- возврат на пройденный шаг
def test_back_to_point_with_other_point_resets_oil_and_slot(
    auth, client_user, ready_draft, second_point
):
    api = auth(client_user)

    response = step(api, ready_draft.pk, "select-point", {"service_point_id": str(second_point.pk)})

    assert response.status_code == 200, response.data
    assert response.data["step"] == DraftStep.POINT_SELECTED
    assert response.data["oil"] is None
    assert response.data["slot_start"] is None
    assert response.data["next_action"] == "select_oil"


def test_back_to_point_with_same_point_keeps_everything(auth, client_user, ready_draft, point):
    api = auth(client_user)
    response = step(api, ready_draft.pk, "select-point", {"service_point_id": str(point.pk)})

    assert response.status_code == 200
    assert response.data["step"] == DraftStep.SLOT_SELECTED
    assert response.data["oil"]["id"] == str(ready_draft.oil_id)
    assert response.data["slot_start"] is not None


def test_changing_oil_keeps_chosen_time(auth, client_user, ready_draft, second_oil):
    response = step(auth(client_user), ready_draft.pk, "select-oil", {"oil_id": str(second_oil.pk)})

    assert response.status_code == 200, response.data
    assert response.data["oil"]["id"] == str(second_oil.pk)
    assert response.data["step"] == DraftStep.SLOT_SELECTED
    assert response.data["next_action"] == "confirm"


def test_changing_point_releases_held_oil_and_slot(
    auth, client_user, other_user, ready_draft, second_point, point, stock, free_slot
):
    """Резерв прежней точки освобождается сразу, а не когда истечёт таймер."""
    api = auth(client_user)
    step(api, ready_draft.pk, "select-point", {"service_point_id": str(second_point.pk)})

    other = draft_service.start_draft(other_user)
    draft_service.select_point(other_user, other.pk, point.pk)
    draft_service.select_oil(other_user, other.pk, stock.oil_id)
    held = draft_service.select_slot(other_user, other.pk, free_slot.start_at)
    assert held.step == DraftStep.SLOT_SELECTED


def test_changing_slot_again(auth, client_user, ready_draft, free_slot):
    later = free_slot.start_at + timedelta(minutes=30)

    api = auth(client_user)
    response = step(api, ready_draft.pk, "select-slot", {"start_at": later.isoformat()})

    assert response.status_code == 200, response.data
    assert response.data["step"] == DraftStep.SLOT_SELECTED


def test_forward_steps_still_cannot_be_skipped(auth, client_user, point, free_slot):
    api = auth(client_user)
    draft = draft_service.start_draft(client_user)
    step(api, draft.pk, "select-point", {"service_point_id": str(point.pk)})

    response = step(api, draft.pk, "select-slot", {"start_at": free_slot.start_at.isoformat()})

    assert response.status_code == 400
    assert response.data["error"]["code"] == "draft_wrong_step"


def test_going_back_does_not_extend_the_timer(client_user, ready_draft, point, second_point):
    expires = ready_draft.expires_at
    with freeze_time(ready_draft.created_at + timedelta(minutes=2)):
        draft_service.select_point(client_user, ready_draft.pk, second_point.pk)

    assert BookingDraft.objects.get(pk=ready_draft.pk).expires_at == expires


# ------------------------------------------------- «подберите на месте»
def test_oil_step_needs_oil_or_on_site(auth, client_user, point):
    api = auth(client_user)
    draft = draft_service.start_draft(client_user)
    step(api, draft.pk, "select-point", {"service_point_id": str(point.pk)})

    response = step(api, draft.pk, "select-oil", {})

    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"


def test_on_site_flow_creates_booking_without_oil(auth, client_user, point, free_slot):
    api = auth(client_user)
    draft = draft_service.start_draft(client_user)
    step(api, draft.pk, "select-point", {"service_point_id": str(point.pk)})

    chosen = step(api, draft.pk, "select-oil", {"on_site": True})
    assert chosen.status_code == 200, chosen.data
    assert chosen.data["oil"] is None
    assert chosen.data["oil_on_site"] is True
    assert chosen.data["next_action"] == "select_slot"

    step(api, draft.pk, "select-slot", {"start_at": free_slot.start_at.isoformat()})
    created = step(api, draft.pk, "confirm")

    assert created.status_code == 201, created.data
    assert created.data["oil_on_site"] is True
    assert created.data["oil_title"] == ON_SITE_OIL_TITLE
    booking = Booking.objects.get(pk=created.data["id"])
    assert booking.oil_id is None
    assert booking.total_price == Decimal(0)


def test_on_site_booking_does_not_hold_any_oil(on_site_booking, auth, other_user, point, stock):
    """Канистра не держится: какое масло будет — неизвестно до звонка."""
    api = auth(other_user)
    oils = api.get(reverse("v1:booking:point-oils", args=[point.pk])).data

    assert [o["id"] for o in oils] == [str(stock.oil_id)]


def test_on_site_sms_says_oil_will_be_chosen(on_site_booking):
    sms = Notification.objects.get(kind=NotificationKind.BOOKING_CREATED)

    assert ON_SITE_OIL_TITLE in sms.text


def test_choosing_oil_back_from_on_site(auth, client_user, point, stock):
    api = auth(client_user)
    draft = draft_service.start_draft(client_user)
    step(api, draft.pk, "select-point", {"service_point_id": str(point.pk)})
    step(api, draft.pk, "select-oil", {"on_site": True})

    response = step(api, draft.pk, "select-oil", {"oil_id": str(stock.oil_id)})

    assert response.data["oil"]["id"] == str(stock.oil_id)
    assert response.data["oil_on_site"] is False


def test_master_sees_booking_needs_oil(auth, master_user, on_site_booking):
    body = auth(master_user).get(master_url("detail", on_site_booking.pk)).json()

    assert body["needs_oil"] is True
    assert body["oil_title"] == ON_SITE_OIL_TITLE


def test_master_sets_oil_with_prices_and_history(auth, master_user, on_site_booking, stock):
    response = auth(master_user).post(
        master_url("set-oil", on_site_booking.pk), {"oil": str(stock.oil_id)}, format="json"
    )

    assert response.status_code == 200, response.data
    assert response.data["needs_oil"] is False
    assert response.data["total_price"] == "4800.00"
    booking = Booking.objects.get(pk=on_site_booking.pk)
    assert booking.oil_id == stock.oil_id
    assert booking.status_logs.filter(comment__startswith="Масло: Shell").exists()


def test_master_cannot_set_oil_out_of_stock(auth, master_user, on_site_booking, stock):
    OilStock.objects.filter(pk=stock.pk).update(quantity=0)

    response = auth(master_user).post(
        master_url("set-oil", on_site_booking.pk), {"oil": str(stock.oil_id)}, format="json"
    )

    assert response.status_code == 409
    assert response.data["error"]["code"] == "oil_out_of_stock"


def test_complete_without_oil_is_refused(auth, master_user, on_site_booking):
    response = auth(master_user).post(master_url("complete", on_site_booking.pk), {}, format="json")

    assert response.status_code == 400
    assert response.data["error"]["code"] == "oil_required"
    assert Booking.objects.get(pk=on_site_booking.pk).status == BookingStatus.PENDING


def test_complete_with_oil_chosen_at_checkout(auth, master_user, on_site_booking, stock):
    response = auth(master_user).post(
        master_url("complete", on_site_booking.pk), {"oil": str(stock.oil_id)}, format="json"
    )

    assert response.status_code == 200, response.data
    assert response.data["status"] == BookingStatus.COMPLETED
    assert response.data["final_price"] == "4800.00"
    stock.refresh_from_db()
    assert stock.quantity == 0


def test_funnel_counts_on_site_as_oil_step(on_site_booking):
    stats = _funnel(BookingDraft.objects.all())

    assert stats["oil_selected"] == 1
