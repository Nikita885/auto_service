"""Сценарий записи: шаги, удержание слота и пятиминутный таймер."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from freezegun import freeze_time

from apps.booking.constants import BookingStatus, DraftCloseReason, DraftStep
from apps.booking.models import Booking, BookingDraft
from apps.booking.services import draft as draft_service
from apps.booking.tasks import expire_stale_drafts
from apps.notifications.models import Notification, NotificationKind

pytestmark = pytest.mark.django_db(transaction=True)


def start(api):
    return api.post(reverse("v1:booking:booking-draft-list"), {}, format="json")


def step(api, draft_id, name, body=None):
    url = reverse(f"v1:booking:booking-draft-{name}", args=[draft_id])
    return api.post(url, body or {}, format="json")


def slot_starts(api, point, day):
    """Свободное время точки за день — как его видит клиент.

    Сравниваем именно datetime, а не строки: DRF сериализует UTC как `Z`,
    а `isoformat()` — как `+00:00`, и строковое сравнение молча «проходит».
    """
    response = api.get(
        reverse("v1:booking:point-slots", args=[point.pk]) + f"?date={day.isoformat()}"
    )
    assert response.status_code == 200, response.data
    return [parse_datetime(s["start_at"]) for s in response.data["slots"]]


# ------------------------------------------------------------- happy path
def test_full_flow_creates_booking(auth, client_user, point, stock, free_slot):
    api = auth(client_user)

    created = start(api)
    assert created.status_code == 201
    draft_id = created.data["id"]
    assert created.data["step"] == DraftStep.STARTED
    assert created.data["next_action"] == "select_point"
    assert 0 < created.data["seconds_left"] <= 300

    after_point = step(api, draft_id, "select-point", {"service_point_id": str(point.pk)})
    assert after_point.data["step"] == DraftStep.POINT_SELECTED
    assert after_point.data["service_point"]["id"] == str(point.pk)

    after_oil = step(api, draft_id, "select-oil", {"oil_id": str(stock.oil_id)})
    assert after_oil.data["step"] == DraftStep.OIL_SELECTED
    assert after_oil.data["oil"]["id"] == str(stock.oil_id)

    after_slot = step(
        api, draft_id, "select-slot", {"start_at": free_slot.start_at.isoformat()}
    )
    assert after_slot.data["step"] == DraftStep.SLOT_SELECTED
    assert after_slot.data["next_action"] == "confirm"

    confirmed = step(api, draft_id, "confirm", {"comment": "Приеду вовремя"})
    assert confirmed.status_code == 201

    booking = Booking.objects.get()
    assert booking.status == BookingStatus.PENDING
    assert booking.user == client_user
    # Снимок данных: имя, машина и цена зафиксированы на момент брони.
    assert booking.client_phone == client_user.phone
    assert booking.car_plate == client_user.car_plate
    assert booking.oil_title == str(stock.oil)
    assert booking.total_price == stock.oil.price + stock.oil.work_price

    draft = BookingDraft.objects.get()
    assert draft.is_open is False
    assert draft.step == DraftStep.CONFIRMED
    assert draft.close_reason == DraftCloseReason.CONFIRMED
    assert draft.booking_id == booking.pk

    assert Notification.objects.filter(
        kind=NotificationKind.BOOKING_CREATED, booking=booking
    ).exists()


def test_draft_appears_immediately_on_start(auth, client_user):
    api = auth(client_user)
    start(api)

    current = api.get(reverse("v1:booking:booking-draft-current"))

    assert current.status_code == 200
    assert current.data["step"] == DraftStep.STARTED
    assert current.data["progress"] == {"completed": 0, "total": 4}
    assert current.data["is_alive"] is True


def test_no_draft_returns_204(auth, client_user):
    assert auth(client_user).get(
        reverse("v1:booking:booking-draft-current")
    ).status_code == 204


# ------------------------------------------------------------ порядок шагов
def test_steps_cannot_be_skipped(auth, client_user, stock):
    api = auth(client_user)
    draft_id = start(api).data["id"]

    response = step(api, draft_id, "select-oil", {"oil_id": str(stock.oil_id)})

    assert response.status_code == 400
    assert response.data["error"]["code"] == "draft_wrong_step"
    assert response.data["error"]["details"]["expected_step"] == DraftStep.POINT_SELECTED


def test_confirm_requires_all_steps(auth, client_user, point):
    api = auth(client_user)
    draft_id = start(api).data["id"]
    step(api, draft_id, "select-point", {"service_point_id": str(point.pk)})

    response = step(api, draft_id, "confirm")

    assert response.status_code == 400
    assert response.data["error"]["code"] == "draft_wrong_step"


# ------------------------------------------------------------- один черновик
def test_second_start_returns_same_draft(auth, client_user):
    api = auth(client_user)

    first = start(api).data["id"]
    second = start(api).data["id"]

    assert first == second
    assert BookingDraft.objects.count() == 1


def test_restart_opens_new_draft(auth, client_user):
    api = auth(client_user)
    first = start(api).data["id"]

    second = api.post(
        reverse("v1:booking:booking-draft-list"), {"restart": True}, format="json"
    ).data["id"]

    assert first != second
    assert BookingDraft.objects.filter(is_open=True).count() == 1
    assert BookingDraft.objects.get(pk=first).close_reason == DraftCloseReason.RESTARTED


# ---------------------------------------------------------------- таймер
def test_draft_expires_after_ttl(auth, client_user, point, settings):
    api = auth(client_user)
    draft_id = start(api).data["id"]

    ttl = settings.BOOKING["DRAFT_TTL_SECONDS"]
    with freeze_time(timezone.now() + timedelta(seconds=ttl + 1)):
        response = step(api, draft_id, "select-point", {"service_point_id": str(point.pk)})

        assert response.status_code == 410
        assert response.data["error"]["code"] == "draft_expired"
        assert api.get(reverse("v1:booking:booking-draft-current")).status_code == 204

    assert BookingDraft.objects.get(pk=draft_id).step == DraftStep.EXPIRED


def test_expired_draft_cannot_be_confirmed(auth, client_user, ready_draft, settings):
    api = auth(client_user)

    ttl = settings.BOOKING["DRAFT_TTL_SECONDS"]
    with freeze_time(timezone.now() + timedelta(seconds=ttl + 1)):
        response = step(api, ready_draft.pk, "confirm")

    assert response.status_code == 410
    assert Booking.objects.count() == 0


def test_timer_does_not_reset_on_steps(auth, client_user, point, stock):
    """Шаги не продлевают жизнь черновика — иначе слот можно держать вечно."""
    api = auth(client_user)
    draft_id = start(api).data["id"]
    expires_at = BookingDraft.objects.get(pk=draft_id).expires_at

    with freeze_time(timezone.now() + timedelta(seconds=60)):
        step(api, draft_id, "select-point", {"service_point_id": str(point.pk)})
        step(api, draft_id, "select-oil", {"oil_id": str(stock.oil_id)})

    assert BookingDraft.objects.get(pk=draft_id).expires_at == expires_at


def test_celery_task_closes_stale_drafts(client_user, settings):
    draft = draft_service.start_draft(client_user)

    with freeze_time(timezone.now() + timedelta(seconds=settings.BOOKING["DRAFT_TTL_SECONDS"] + 1)):
        assert expire_stale_drafts() == 1

    draft.refresh_from_db()
    assert draft.is_open is False
    assert draft.close_reason == DraftCloseReason.EXPIRED


# ------------------------------------------------------------- удержание
def test_draft_holds_the_slot(
    auth, client_user, other_user, point, stock, free_slot, ready_draft
):
    """Пост один: пока первый клиент заполняет форму, время недоступно другим."""
    api = auth(other_user)
    day = free_slot.start_at.astimezone(point.tz).date()

    assert slot_starts(api, point, day), "остальные слоты дня должны остаться свободны"
    assert free_slot.start_at not in slot_starts(api, point, day)


def test_draft_holds_the_oil(auth, other_user, point, stock, client_user):
    """На складе одна канистра — второй клиент её уже не увидит."""
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_oil(client_user, draft.pk, stock.oil_id)

    api = auth(other_user)
    response = api.get(reverse("v1:booking:point-oils", args=[point.pk]))

    assert response.data == []


def test_cancelled_draft_releases_the_slot(
    auth, client_user, other_user, point, stock, free_slot, ready_draft
):
    api = auth(other_user)
    day = free_slot.start_at.astimezone(point.tz).date()
    assert free_slot.start_at not in slot_starts(api, point, day)

    draft_service.cancel_draft(client_user, ready_draft.pk)

    assert free_slot.start_at in slot_starts(api, point, day)


def test_expired_draft_releases_the_slot(
    client_user, other_user, point, stock, free_slot, ready_draft, settings
):
    from apps.booking.services.slots import build_slots

    day = free_slot.start_at.astimezone(point.tz).date()
    assert not [s for s in build_slots(point, day) if s.start_at == free_slot.start_at]

    with freeze_time(timezone.now() + timedelta(seconds=settings.BOOKING["DRAFT_TTL_SECONDS"] + 1)):
        expire_stale_drafts()
        freed = [s for s in build_slots(point, day) if s.start_at == free_slot.start_at]

    assert freed


def test_slot_taken_between_steps_gives_409(
    auth, client_user, other_user, point, stock, free_slot, ready_draft
):
    """Пока клиент думал, время занял другой — узнаём об этом на подтверждении."""
    OilStock = stock.__class__
    OilStock.objects.filter(pk=stock.pk).update(quantity=5)

    second = draft_service.start_draft(other_user)
    draft_service.select_point(other_user, second.pk, point.pk)
    draft_service.select_oil(other_user, second.pk, stock.oil_id)
    # Черновик первого клиента удерживает слот, поэтому второй его не выберет.
    # Имитируем гонку: первый подтверждает после того, как слот занят бронью.
    Booking.objects.create(
        user=other_user,
        service_point=point,
        oil=stock.oil,
        start_at=free_slot.start_at,
        end_at=free_slot.end_at,
        client_phone=other_user.phone,
        oil_title=str(stock.oil),
        oil_price=stock.oil.price,
        work_price=stock.oil.work_price,
        total_price=stock.oil.total_price,
    )

    response = step(auth(client_user), ready_draft.pk, "confirm")

    assert response.status_code == 409
    assert response.data["error"]["code"] == "slot_taken"


def test_out_of_stock_oil_cannot_be_selected(auth, client_user, point, stock):
    stock.__class__.objects.filter(pk=stock.pk).update(quantity=0)

    api = auth(client_user)
    draft_id = start(api).data["id"]
    step(api, draft_id, "select-point", {"service_point_id": str(point.pk)})

    response = step(api, draft_id, "select-oil", {"oil_id": str(stock.oil_id)})

    assert response.status_code == 409
    assert response.data["error"]["code"] == "oil_out_of_stock"


# ---------------------------------------------------------------- доступ
def test_foreign_draft_is_not_visible(auth, other_user, ready_draft):
    response = step(auth(other_user), ready_draft.pk, "confirm")

    assert response.status_code == 404
    assert response.data["error"]["code"] == "draft_not_found"


def test_anonymous_cannot_start_draft(api):
    assert start(api).status_code == 401
