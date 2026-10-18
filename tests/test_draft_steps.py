"""Переход на пройденный шаг записи и «подберите услугу на месте».

Вперёд шаги идут по порядку, назад — на любой пройденный, без потери
таймера. «Подберите на месте» — запись без услуги, которая стоит в
очереди звонков у мастера, пока он не выберет услугу вместе с клиентом.
Разрешает это категория: для мойки выбирать нечего.
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
from apps.booking.services.booking import ON_SITE_TITLE
from apps.catalog.models import Service, ServiceCategory
from apps.master.metrics import _funnel
from apps.notifications.models import Notification, NotificationKind

pytestmark = pytest.mark.django_db(transaction=True)


def step(api, draft_id, name, body=None):
    url = reverse(f"v1:booking:booking-draft-{name}", args=[draft_id])
    return api.post(url, body or {}, format="json")


def master_url(name, *args):
    return reverse(f"v1:master:master-booking-{name}", args=args)


@pytest.fixture
def second_service(category) -> Service:
    """Вторая услуга в той же категории — её остаток не ограничен."""
    return Service.objects.create(
        category=category,
        name="Mobil Super 3000 5W-40, 4.0 л",
        price=Decimal("4300"),
        material_price=Decimal("3500"),
        is_limited=True,
        quantity=3,
    )


@pytest.fixture
def wash(point) -> Service:
    """Мойка: своя категория, выбирать на месте нечего, остаток не ведём."""
    category = ServiceCategory.objects.create(
        service_point=point, name="Мойка", journal_kind="wash", allow_on_site=False
    )
    return Service.objects.create(
        category=category, name="Мойка кузова", price=Decimal("600")
    )


@pytest.fixture
def on_site_booking(client_user, point, category, free_slot):
    """Запись «подберите на месте»: услуги нет, цены нулевые."""
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_category(client_user, draft.pk, category.pk)
    draft_service.select_service(client_user, draft.pk, on_site=True)
    draft_service.select_slot(client_user, draft.pk, free_slot.start_at)
    return draft_service.confirm(client_user, draft.pk)


# ------------------------------------------------- возврат на пройденный шаг
def test_back_to_point_with_other_point_resets_service_and_slot(
    auth, client_user, ready_draft, second_point
):
    api = auth(client_user)

    response = step(
        api, ready_draft.pk, "select-point", {"service_point_id": str(second_point.pk)}
    )

    assert response.status_code == 200, response.data
    assert response.data["step"] == DraftStep.POINT_SELECTED
    assert response.data["service_category"] is None
    assert response.data["service"] is None
    assert response.data["slot_start"] is None
    assert response.data["next_action"] == "select_category"


def test_back_to_point_with_same_point_keeps_everything(
    auth, client_user, ready_draft, point
):
    api = auth(client_user)
    response = step(api, ready_draft.pk, "select-point", {"service_point_id": str(point.pk)})

    assert response.status_code == 200
    assert response.data["step"] == DraftStep.SLOT_SELECTED
    assert response.data["service"]["id"] == str(ready_draft.service_id)
    assert response.data["slot_start"] is not None


def test_changing_service_keeps_chosen_time(auth, client_user, ready_draft, second_service):
    response = step(
        auth(client_user), ready_draft.pk, "select-service",
        {"service_id": str(second_service.pk)},
    )

    assert response.status_code == 200, response.data
    assert response.data["service"]["id"] == str(second_service.pk)
    assert response.data["step"] == DraftStep.SLOT_SELECTED
    assert response.data["next_action"] == "confirm"


def test_changing_category_resets_service_but_keeps_time(
    auth, client_user, ready_draft, wash
):
    """Услуга из другой категории в записи не окажется, а время остаётся."""
    api = auth(client_user)

    response = step(
        api, ready_draft.pk, "select-category", {"category_id": str(wash.category_id)}
    )

    assert response.status_code == 200, response.data
    assert response.data["service"] is None
    assert response.data["slot_start"] is not None
    assert response.data["next_action"] == "select_service"


def test_service_from_another_category_is_refused(auth, client_user, ready_draft, wash):
    api = auth(client_user)
    step(api, ready_draft.pk, "select-category", {"category_id": str(wash.category_id)})

    response = step(
        api, ready_draft.pk, "select-service", {"service_id": str(ready_draft.service_id)}
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "service_other_category"


def test_changing_point_releases_held_service_and_slot(
    auth, client_user, other_user, ready_draft, second_point, point, service, free_slot
):
    """Резерв прежней точки освобождается сразу, а не когда истечёт таймер."""
    api = auth(client_user)
    step(api, ready_draft.pk, "select-point", {"service_point_id": str(second_point.pk)})

    other = draft_service.start_draft(other_user)
    draft_service.select_point(other_user, other.pk, point.pk)
    draft_service.select_category(other_user, other.pk, service.category_id)
    draft_service.select_service(other_user, other.pk, service.pk)
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
def test_service_step_needs_service_or_on_site(auth, client_user, point, category):
    api = auth(client_user)
    draft = draft_service.start_draft(client_user)
    step(api, draft.pk, "select-point", {"service_point_id": str(point.pk)})
    step(api, draft.pk, "select-category", {"category_id": str(category.pk)})

    response = step(api, draft.pk, "select-service", {})

    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"


def test_on_site_flow_creates_booking_without_service(
    auth, client_user, point, category, free_slot
):
    api = auth(client_user)
    draft = draft_service.start_draft(client_user)
    step(api, draft.pk, "select-point", {"service_point_id": str(point.pk)})
    step(api, draft.pk, "select-category", {"category_id": str(category.pk)})

    chosen = step(api, draft.pk, "select-service", {"on_site": True})
    assert chosen.status_code == 200, chosen.data
    assert chosen.data["service"] is None
    assert chosen.data["on_site"] is True
    assert chosen.data["next_action"] == "select_slot"

    step(api, draft.pk, "select-slot", {"start_at": free_slot.start_at.isoformat()})
    created = step(api, draft.pk, "confirm")

    assert created.status_code == 201, created.data
    assert created.data["oil_on_site"] is True
    assert created.data["service_title"] == ON_SITE_TITLE
    assert created.data["category_title"] == category.name
    booking = Booking.objects.get(pk=created.data["id"])
    assert not booking.items.exists()
    assert booking.service_on_site is True
    assert booking.total_price == Decimal(0)


def test_on_site_is_refused_where_category_forbids_it(
    auth, client_user, point, wash, free_slot
):
    """У мойки подбирать нечего: записаться без услуги нельзя."""
    api = auth(client_user)
    draft = draft_service.start_draft(client_user)
    step(api, draft.pk, "select-point", {"service_point_id": str(point.pk)})
    step(api, draft.pk, "select-category", {"category_id": str(wash.category_id)})

    response = step(api, draft.pk, "select-service", {"on_site": True})

    assert response.status_code == 400
    assert response.data["error"]["code"] == "on_site_not_allowed"


def test_on_site_booking_does_not_hold_any_service(
    on_site_booking, auth, other_user, point, service
):
    """Остаток не держится: какая услуга понадобится — неизвестно до звонка."""
    api = auth(other_user)
    rows = api.get(reverse("v1:booking:point-services", args=[point.pk])).data

    assert [row["id"] for row in rows] == [str(service.pk)]


def test_on_site_sms_says_service_will_be_chosen(on_site_booking):
    sms = Notification.objects.get(kind=NotificationKind.BOOKING_CREATED)

    assert ON_SITE_TITLE in sms.text


def test_choosing_service_back_from_on_site(auth, client_user, point, service):
    api = auth(client_user)
    draft = draft_service.start_draft(client_user)
    step(api, draft.pk, "select-point", {"service_point_id": str(point.pk)})
    step(api, draft.pk, "select-category", {"category_id": str(service.category_id)})
    step(api, draft.pk, "select-service", {"on_site": True})

    response = step(api, draft.pk, "select-service", {"service_id": str(service.pk)})

    assert response.data["service"]["id"] == str(service.pk)
    assert response.data["on_site"] is False


def test_master_sees_booking_needs_service(auth, master_user, on_site_booking):
    body = auth(master_user).get(master_url("detail", on_site_booking.pk)).json()

    assert body["needs_service"] is True
    assert body["service_title"] == ON_SITE_TITLE
    assert body["services"] == []


def test_master_sets_service_with_prices_and_history(
    auth, master_user, on_site_booking, service
):
    response = auth(master_user).post(
        master_url("set-service", on_site_booking.pk),
        {"service": str(service.pk)},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["needs_service"] is False
    assert response.data["total_price"] == "4800.00"
    booking = Booking.objects.get(pk=on_site_booking.pk)
    assert [item.service_id for item in booking.items.all()] == [service.pk]
    assert booking.service_on_site is False
    assert booking.status_logs.filter(comment__startswith="Услуга: Shell").exists()


def test_master_cannot_set_service_out_of_stock(
    auth, master_user, on_site_booking, service
):
    Service.objects.filter(pk=service.pk).update(quantity=0)

    response = auth(master_user).post(
        master_url("set-service", on_site_booking.pk),
        {"service": str(service.pk)},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["error"]["code"] == "service_out_of_stock"


def test_master_sets_service_by_old_oil_api(auth, master_user, on_site_booking, stock):
    """Панель прежней версии шлёт масло — запись получает ту же услугу."""
    response = auth(master_user).post(
        master_url("set-oil", on_site_booking.pk), {"oil": str(stock.oil_id)}, format="json"
    )

    assert response.status_code == 200, response.data
    assert response.data["needs_oil"] is False
    booking = Booking.objects.get(pk=on_site_booking.pk)
    assert booking.items.get().service.oil_id == stock.oil_id


def test_complete_without_service_is_refused(auth, master_user, on_site_booking):
    response = auth(master_user).post(master_url("complete", on_site_booking.pk), {}, format="json")

    assert response.status_code == 400
    assert response.data["error"]["code"] == "service_required"
    assert Booking.objects.get(pk=on_site_booking.pk).status == BookingStatus.PENDING


def test_complete_with_service_chosen_at_checkout(
    auth, master_user, on_site_booking, service
):
    response = auth(master_user).post(
        master_url("complete", on_site_booking.pk),
        {"service": str(service.pk)},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["status"] == BookingStatus.COMPLETED
    assert response.data["final_price"] == "4800.00"
    service.refresh_from_db()
    assert service.quantity == 0


def test_unlimited_service_is_not_written_off(
    auth, master_user, client_user, point, wash, free_slot
):
    """У мойки остатка нет — списывать нечего, и ноль в минус не уходит."""
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_category(client_user, draft.pk, wash.category_id)
    draft_service.select_service(client_user, draft.pk, wash.pk)
    draft_service.select_slot(client_user, draft.pk, free_slot.start_at)
    booking = draft_service.confirm(client_user, draft.pk)

    response = auth(master_user).post(master_url("complete", booking.pk), {}, format="json")

    assert response.status_code == 200, response.data
    wash.refresh_from_db()
    assert wash.quantity == 0


def test_funnel_counts_on_site_as_service_step(on_site_booking):
    stats = _funnel(BookingDraft.objects.all())

    assert stats["category_selected"] == 1
    assert stats["service_selected"] == 1


# ----------------------------------------------- черновик со старым шагом
def test_draft_left_on_legacy_oil_step_still_moves(auth, client_user, ready_draft, free_slot):
    """Черновик, застрявший на шаге масла в момент выкатки, не падает с 500.

    Живёт он до пяти минут, а `oil_selected` в порядке шагов больше нет.
    """
    BookingDraft.objects.filter(pk=ready_draft.pk).update(
        step=DraftStep.OIL_SELECTED, slot_start=None
    )

    current = auth(client_user).get(reverse("v1:booking:booking-draft-current"))
    assert current.status_code == 200
    assert current.data["next_action"] == "select_slot"
    assert current.data["progress"]["completed"] == 3

    moved = step(
        auth(client_user), ready_draft.pk, "select-slot",
        {"start_at": free_slot.start_at.isoformat()},
    )
    assert moved.status_code == 200, moved.data
    assert moved.data["step"] == DraftStep.SLOT_SELECTED
