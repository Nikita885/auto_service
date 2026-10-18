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
def test_full_flow_creates_booking(auth, client_user, point, service, free_slot):
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

    after_category = step(
        api, draft_id, "select-category", {"category_id": str(service.category_id)}
    )
    assert after_category.data["step"] == DraftStep.CATEGORY_SELECTED
    assert after_category.data["service_category"]["id"] == str(service.category_id)
    assert after_category.data["next_action"] == "select_service"

    after_service = step(api, draft_id, "select-service", {"service_id": str(service.pk)})
    assert after_service.data["step"] == DraftStep.SERVICE_SELECTED
    assert after_service.data["service"]["id"] == str(service.pk)
    # Цен клиенту не показываем нигде, включая JSON.
    assert "price" not in after_service.data["service"]

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
    assert booking.car_plate == "А123ВС77"
    assert booking.car.is_primary  # не выбрал машину — основная
    assert booking.service_title == service.name
    assert booking.category_title == service.category.name
    assert booking.total_price == service.price
    assert booking.material_price == service.material_price
    assert [(item.title, item.price) for item in booking.items.all()] == [
        (service.name, service.price)
    ]

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
    assert current.data["progress"] == {"completed": 0, "total": 5}
    assert current.data["is_alive"] is True


def test_no_draft_returns_204(auth, client_user):
    assert auth(client_user).get(
        reverse("v1:booking:booking-draft-current")
    ).status_code == 204


# ------------------------------------------------------------ порядок шагов
def test_steps_cannot_be_skipped(auth, client_user, service):
    api = auth(client_user)
    draft_id = start(api).data["id"]

    response = step(
        api, draft_id, "select-category", {"category_id": str(service.category_id)}
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "draft_wrong_step"
    assert response.data["error"]["details"]["expected_step"] == DraftStep.POINT_SELECTED


def test_service_step_needs_category_first(auth, client_user, point, service):
    api = auth(client_user)
    draft_id = start(api).data["id"]
    step(api, draft_id, "select-point", {"service_point_id": str(point.pk)})

    response = step(api, draft_id, "select-service", {"service_id": str(service.pk)})

    assert response.status_code == 400
    assert response.data["error"]["details"]["expected_step"] == DraftStep.CATEGORY_SELECTED


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


def test_timer_does_not_reset_on_steps(auth, client_user, point, service):
    """Шаги не продлевают жизнь черновика — иначе слот можно держать вечно."""
    api = auth(client_user)
    draft_id = start(api).data["id"]
    expires_at = BookingDraft.objects.get(pk=draft_id).expires_at

    with freeze_time(timezone.now() + timedelta(seconds=60)):
        step(api, draft_id, "select-point", {"service_point_id": str(point.pk)})
        step(api, draft_id, "select-category", {"category_id": str(service.category_id)})
        step(api, draft_id, "select-service", {"service_id": str(service.pk)})

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
    auth, client_user, other_user, point, service, free_slot, ready_draft
):
    """Пост один: пока первый клиент заполняет форму, время недоступно другим."""
    api = auth(other_user)
    day = free_slot.start_at.astimezone(point.tz).date()

    assert slot_starts(api, point, day), "остальные слоты дня должны остаться свободны"
    assert free_slot.start_at not in slot_starts(api, point, day)


def test_draft_holds_the_service(auth, other_user, point, service, client_user):
    """Остаток один — второй клиент эту услугу уже не увидит."""
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_category(client_user, draft.pk, service.category_id)
    draft_service.select_service(client_user, draft.pk, service.pk)

    api = auth(other_user)
    services = api.get(reverse("v1:booking:point-services", args=[point.pk]))
    oils = api.get(reverse("v1:booking:point-oils", args=[point.pk]))

    assert services.data == []
    # Старое API отвечает из тех же услуг — и так же пусто.
    assert oils.data == []


def test_unlimited_service_never_runs_out(auth, client_user, other_user, point, service):
    """У мойки остатка нет: сколько бы её ни выбрали, она остаётся доступной."""
    service.is_limited = False
    service.quantity = 0
    service.save(update_fields=["is_limited", "quantity"])

    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_category(client_user, draft.pk, service.category_id)
    draft_service.select_service(client_user, draft.pk, service.pk)

    response = auth(other_user).get(
        reverse("v1:booking:point-services", args=[point.pk])
    )

    assert [row["id"] for row in response.data] == [str(service.pk)]


def test_cancelled_draft_releases_the_slot(
    auth, client_user, other_user, point, service, free_slot, ready_draft
):
    api = auth(other_user)
    day = free_slot.start_at.astimezone(point.tz).date()
    assert free_slot.start_at not in slot_starts(api, point, day)

    draft_service.cancel_draft(client_user, ready_draft.pk)

    assert free_slot.start_at in slot_starts(api, point, day)


def test_expired_draft_releases_the_slot(
    client_user, other_user, point, service, free_slot, ready_draft, settings
):
    from apps.booking.services.slots import build_slots

    day = free_slot.start_at.astimezone(point.tz).date()
    assert not [s for s in build_slots(point, day) if s.start_at == free_slot.start_at]

    with freeze_time(timezone.now() + timedelta(seconds=settings.BOOKING["DRAFT_TTL_SECONDS"] + 1)):
        expire_stale_drafts()
        freed = [s for s in build_slots(point, day) if s.start_at == free_slot.start_at]

    assert freed


def test_slot_taken_between_steps_gives_409(
    auth, client_user, other_user, point, service, free_slot, ready_draft
):
    """Пока клиент думал, время занял другой — узнаём об этом на подтверждении."""
    service.__class__.objects.filter(pk=service.pk).update(quantity=5)

    second = draft_service.start_draft(other_user)
    draft_service.select_point(other_user, second.pk, point.pk)
    draft_service.select_category(other_user, second.pk, service.category_id)
    draft_service.select_service(other_user, second.pk, service.pk)
    # Черновик первого клиента удерживает слот, поэтому второй его не выберет.
    # Имитируем гонку: первый подтверждает после того, как слот занят бронью.
    Booking.objects.create(
        user=other_user,
        service_point=point,
        service_category=service.category,
        start_at=free_slot.start_at,
        end_at=free_slot.end_at,
        client_phone=other_user.phone,
        category_title=service.category.name,
        service_title=service.name,
        oil_title=service.name,
        oil_price=service.material_price,
        material_price=service.material_price,
        work_price=service.work_price,
        total_price=service.price,
    )

    response = step(auth(client_user), ready_draft.pk, "confirm")

    assert response.status_code == 409
    assert response.data["error"]["code"] == "slot_taken"


def test_out_of_stock_service_cannot_be_selected(auth, client_user, point, service):
    service.__class__.objects.filter(pk=service.pk).update(quantity=0)

    api = auth(client_user)
    draft_id = start(api).data["id"]
    step(api, draft_id, "select-point", {"service_point_id": str(point.pk)})
    step(api, draft_id, "select-category", {"category_id": str(service.category_id)})

    response = step(api, draft_id, "select-service", {"service_id": str(service.pk)})

    assert response.status_code == 409
    assert response.data["error"]["code"] == "service_out_of_stock"


# ----------------------------------------------------------- старое API
def test_old_oil_api_still_books(auth, client_user, point, service, stock, free_slot):
    """Приложение прежней версии записывает клиента как раньше.

    Оно знает только масла: выбирает из `/oils/`, шлёт `select-oil` — и
    получает ту же запись на услугу, в которую масло перенесли.
    """
    api = auth(client_user)
    draft_id = start(api).data["id"]
    step(api, draft_id, "select-point", {"service_point_id": str(point.pk)})

    oils = api.get(reverse("v1:booking:point-oils", args=[point.pk])).data
    assert [row["id"] for row in oils] == [str(stock.oil_id)]

    chosen = step(api, draft_id, "select-oil", {"oil_id": str(stock.oil_id)})
    assert chosen.data["next_action"] == "select_slot"
    assert chosen.data["service"]["id"] == str(service.pk)

    step(api, draft_id, "select-slot", {"start_at": free_slot.start_at.isoformat()})
    assert step(api, draft_id, "confirm").status_code == 201

    booking = Booking.objects.get()
    assert [item.service_id for item in booking.items.all()] == [service.pk]
    # Старое поле тоже заполнено: откат кода не должен увидеть запись без масла.
    assert booking.oil_id == stock.oil_id


def test_old_oil_api_reports_its_own_error_code(auth, client_user, point, service):
    """Коды ошибок старого API не меняются: их разбирает старое приложение."""
    service.__class__.objects.filter(pk=service.pk).update(quantity=0)
    api = auth(client_user)
    draft_id = start(api).data["id"]
    step(api, draft_id, "select-point", {"service_point_id": str(point.pk)})

    response = step(api, draft_id, "select-oil", {"oil_id": str(service.oil_id)})

    assert response.status_code == 409
    assert response.data["error"]["code"] == "oil_out_of_stock"


# ---------------------------------------------------------------- доступ
def test_foreign_draft_is_not_visible(auth, other_user, ready_draft):
    response = step(auth(other_user), ready_draft.pk, "confirm")

    assert response.status_code == 404
    assert response.data["error"]["code"] == "draft_not_found"


def test_anonymous_cannot_start_draft(api):
    assert start(api).status_code == 401
