"""API услуг: каталог точки, клиент без цен, права мастера, остатки.

Граничные случаи, ради которых этап и пишется: выключенная услуга
пропадает у клиента сразу, но запись не меняется; последняя единица не
достаётся двоим; чужая точка закрыта; цены клиенту не уходят даже в JSON.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.booking.models import Booking
from apps.booking.services import booking as booking_service
from apps.booking.services import draft as draft_service
from apps.catalog.models import OilStock, Service, ServiceCategory
from apps.common.exceptions import ConflictError
from apps.garage.services import journal

pytestmark = pytest.mark.django_db(transaction=True)


def url(name, *args):
    return reverse(f"v1:booking:{name}", args=args)


def master_url(name, *args):
    return reverse(f"v1:master:{name}", args=args)


@pytest.fixture
def admin_user(db) -> User:
    return User.objects.create_superuser(phone="+79000000000", password="admin12345")


@pytest.fixture
def wash(point) -> Service:
    category = ServiceCategory.objects.create(
        service_point=point,
        name="Мойка",
        journal_kind="wash",
        allow_on_site=False,
        sort_order=20,
    )
    return Service.objects.create(category=category, name="Мойка кузова", price=Decimal("600"))


# --------------------------------------------------- клиент: категории и услуги
def test_client_sees_categories_and_services_without_prices(
    auth, client_user, point, service, wash
):
    body = auth(client_user).get(url("point-categories", point.pk)).json()

    assert [c["name"] for c in body] == ["Замена масла", "Мойка"]  # по порядку показа
    assert [s["name"] for s in body[1]["services"]] == ["Мойка кузова"]
    # Цен и остатка клиенту нет нигде, включая JSON: решение заказчика.
    raw = json.dumps(body, ensure_ascii=False)
    for forbidden in ("price", "quantity", "material", "available"):
        assert forbidden not in raw


def test_client_services_endpoint_filters_by_category(auth, client_user, point, service, wash):
    api = auth(client_user)

    only_wash = api.get(url("point-services", point.pk) + f"?category={wash.category_id}").json()
    everything = api.get(url("point-services", point.pk)).json()

    assert [s["name"] for s in only_wash] == ["Мойка кузова"]
    assert len(everything) == 2


def test_other_points_catalog_is_not_visible(auth, client_user, point, second_point, wash):
    """Каталог у каждой точки свой: мойка первой точки на второй не видна."""
    assert auth(client_user).get(url("point-categories", second_point.pk)).json() == []


def test_disabled_service_vanishes_at_once_but_booking_keeps_snapshot(
    auth, master_user, client_user, booking, service
):
    """Выключили услугу — клиенту пропала сразу, а созданная запись не поменялась."""
    Service.objects.filter(pk=service.pk).update(is_active=False, price=Decimal("9999"))

    body = auth(client_user).get(url("point-services", service.category.service_point_id)).json()
    assert body == []

    booking.refresh_from_db()
    assert booking.total_price == Decimal("4800.00")
    assert booking.service_title == service.name
    assert booking.items.get().price == Decimal("4800.00")


def test_disabled_category_is_hidden_with_all_its_services(auth, client_user, point, service):
    ServiceCategory.objects.filter(pk=service.category_id).update(is_active=False)

    assert auth(client_user).get(url("point-categories", point.pk)).json() == []
    # А выбрать её напрямую по id нельзя.
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    from apps.common.exceptions import NotFoundError

    with pytest.raises(NotFoundError) as err:
        draft_service.select_category(client_user, draft.pk, service.category_id)
    assert err.value.code == "category_not_available"


def test_empty_category_is_hidden_unless_on_site_is_allowed(auth, client_user, point, service):
    ServiceCategory.objects.create(service_point=point, name="Пустая", allow_on_site=False)
    ServiceCategory.objects.create(service_point=point, name="Подберём", allow_on_site=True)

    names = [c["name"] for c in auth(client_user).get(url("point-categories", point.pk)).json()]

    assert "Пустая" not in names
    assert "Подберём" in names


def test_sold_out_service_is_hidden_but_unlimited_one_stays(
    auth, client_user, point, service, category
):
    Service.objects.filter(pk=service.pk).update(quantity=0)
    Service.objects.create(category=category, name="Долив", price=Decimal("300"))

    names = [s["name"] for s in auth(client_user).get(url("point-services", point.pk)).json()]

    assert names == ["Долив"]


# ----------------------------------------------------------------- гонка
def test_last_unit_goes_to_the_first_draft_only(client_user, other_user, point, service):
    first = draft_service.start_draft(client_user)
    second = draft_service.start_draft(other_user)
    for user, draft in ((client_user, first), (other_user, second)):
        draft_service.select_point(user, draft.pk, point.pk)
        draft_service.select_category(user, draft.pk, service.category_id)
    draft_service.select_service(client_user, first.pk, service.pk)

    with pytest.raises(ConflictError) as err:
        draft_service.select_service(other_user, second.pk, service.pk)
    assert err.value.code == "service_out_of_stock"


def test_active_booking_holds_the_unit(client_user, other_user, point, service, booking):
    """Запись остаток не уменьшает, но единицу держит — до выполнения."""
    service.refresh_from_db()
    assert service.quantity == 1

    draft = draft_service.start_draft(other_user)
    draft_service.select_point(other_user, draft.pk, point.pk)
    draft_service.select_category(other_user, draft.pk, service.category_id)
    with pytest.raises(ConflictError):
        draft_service.select_service(other_user, draft.pk, service.pk)


def test_own_draft_does_not_block_itself(client_user, point, service, ready_draft):
    """Свой черновик держит единицу, но самому себе услугу не закрывает."""
    again = draft_service.select_service(client_user, ready_draft.pk, service.pk)

    assert again.service_id == service.pk


# ------------------------------------------------------------- списание
def test_completion_writes_off_service_and_old_stock_once(
    auth, master_user, booking, stock, service
):
    api = auth(master_user)
    assert api.post(master_url("master-booking-start", booking.pk)).status_code == 200
    assert (
        api.post(master_url("master-booking-complete", booking.pk), {}, format="json").status_code
        == 200
    )
    # Повторное «Выполнено» не списывает второй раз.
    assert (
        api.post(master_url("master-booking-complete", booking.pk), {}, format="json").status_code
        == 409
    )

    service.refresh_from_db()
    stock.refresh_from_db()
    assert (service.quantity, stock.quantity) == (0, 0)


def test_write_off_never_goes_below_zero(master_user, booking, service, stock):
    """Остаток пересчитали вручную в ноль, пока запись стояла: не падаем."""
    Service.objects.filter(pk=service.pk).update(quantity=0)
    OilStock.objects.filter(pk=stock.pk).update(quantity=0)

    done = booking_service.complete(master_user, booking.pk)

    assert done.status == "completed"
    service.refresh_from_db()
    assert service.quantity == 0


def test_django_admin_stock_edit_reaches_the_service(point, oil, stock, service):
    """Остаток поправили в обход панели — услуга обязана это увидеть."""
    OilStock.objects.filter(pk=stock.pk).first()
    row = OilStock.objects.get(pk=stock.pk)
    row.quantity = 9
    row.save()

    service.refresh_from_db()
    assert service.quantity == 9


# ---------------------------------------------------- мастер: чтение записи
def test_master_sees_prices_and_items(auth, master_user, booking, service):
    body = auth(master_user).get(master_url("master-booking-detail", booking.pk)).json()

    assert body["needs_service"] is False
    assert body["category_title"] == "Замена масла"
    assert body["services"][0]["title"] == service.name
    assert body["services"][0]["price"] == "4800.00"
    assert body["material_price"] == "3900.00"
    assert body["work_price"] == "900.00"


def test_client_booking_json_has_no_prices_of_services(auth, client_user, booking):
    body = auth(client_user).get(url("booking-detail", booking.pk)).json()

    assert body["services"] == [booking.service_title]
    # Итог виден только у выполненной записи; цены позиций — нигде.
    assert body["final_price"] is None
    raw = json.dumps({k: v for k, v in body.items() if k not in ("final_price", "paid_amount")})
    assert "4800" not in raw and "3900" not in raw


# ------------------------------------------------- мастер: каталог и права
def create_category(api, point, **extra):
    return api.post(
        master_url("master-service-category-list"),
        {"service_point": str(point.pk), "name": "Замена резины", **extra},
        format="json",
    )


def test_master_creates_category_and_service_on_own_point(auth, master_user, point):
    api = auth(master_user)

    made = create_category(api, point, sort_order=30, journal_kind="tires")
    assert made.status_code == 201, made.content
    assert made.json()["journal_kind"] == "tires"

    created = api.post(
        master_url("master-service-list"),
        {
            "category": made.json()["id"],
            "name": "Шиномонтаж R16",
            "price": "2400",
            "material_price": "0",
            "is_limited": False,
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    assert created.json()["work_price"] == "2400.00"

    listing = api.get(master_url("master-service-category-list")).json()
    tires = next(c for c in listing if c["name"] == "Замена резины")
    assert [s["name"] for s in tires["services"]] == ["Шиномонтаж R16"]


def test_master_of_another_point_is_refused(auth, master_user, point, second_point):
    """Мастер привязан к одной точке — на чужой каталог не лезет."""
    master_user.service_points.add(point)

    refused = create_category(auth(master_user), second_point)

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "point_not_allowed"
    assert not ServiceCategory.objects.filter(service_point=second_point).exists()


def test_master_cannot_edit_foreign_service(auth, master_user, point, second_point):
    other = ServiceCategory.objects.create(service_point=second_point, name="Мойка")
    foreign = Service.objects.create(category=other, name="Мойка", price=Decimal("500"))
    master_user.service_points.add(point)

    resp = auth(master_user).patch(
        master_url("master-service-detail", foreign.pk), {"price": "1"}, format="json"
    )

    assert resp.status_code == 403
    foreign.refresh_from_db()
    assert foreign.price == Decimal("500.00")


def test_admin_works_on_any_point_and_master_listing_is_scoped(
    auth, admin_user, master_user, point, second_point
):
    assert create_category(auth(admin_user), second_point).status_code == 201
    create_category(auth(admin_user), point, name="Первая")
    master_user.service_points.add(point)

    names = [
        c["name"] for c in auth(master_user).get(master_url("master-service-category-list")).json()
    ]

    assert names == ["Первая"]  # категория чужой точки мастеру не видна


def test_client_cannot_touch_the_catalog(auth, client_user, point):
    assert create_category(auth(client_user), point).status_code == 403
    assert auth(client_user).get(master_url("master-service-category-list")).status_code == 403


def test_material_above_price_is_refused(auth, master_user, category):
    resp = auth(master_user).post(
        master_url("master-service-list"),
        {"category": str(category.pk), "name": "Ошибка", "price": "100", "material_price": "200"},
        format="json",
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "material_above_price"


def test_price_edit_below_material_is_refused(auth, master_user, service):
    resp = auth(master_user).patch(
        master_url("master-service-detail", service.pk), {"price": "100"}, format="json"
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "material_above_price"
    service.refresh_from_db()
    assert service.price == Decimal("4800.00")


def test_duplicate_names_conflict(auth, master_user, point, category, service):
    again = auth(master_user).post(
        master_url("master-service-list"),
        {"category": str(category.pk), "name": service.name, "price": "1"},
        format="json",
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "service_exists"

    dup_category = create_category(auth(master_user), point, name="Замена масла")
    assert dup_category.status_code == 409
    assert dup_category.json()["error"]["code"] == "category_exists"


def test_stock_edit_is_absolute_and_repeat_is_idempotent(auth, master_user, service):
    api = auth(master_user)
    for _ in range(2):  # двойное нажатие не задваивает приход
        resp = api.patch(
            master_url("master-service-detail", service.pk), {"quantity": 7}, format="json"
        )
        assert resp.status_code == 200
    service.refresh_from_db()
    assert service.quantity == 7


def test_new_price_does_not_touch_existing_bookings(auth, master_user, booking, service):
    auth(master_user).patch(
        master_url("master-service-detail", service.pk), {"price": "9000"}, format="json"
    )

    booking.refresh_from_db()
    assert booking.total_price == Decimal("4800.00")
    assert booking.items.get().price == Decimal("4800.00")


def test_unknown_ids_are_404_not_500(auth, master_user):
    import uuid

    api = auth(master_user)
    assert (
        api.patch(
            master_url("master-service-detail", uuid.uuid4()), {"price": "1"}, format="json"
        ).status_code
        == 404
    )
    assert (
        api.patch(
            master_url("master-service-category-detail", uuid.uuid4()), {"name": "x"}, format="json"
        ).status_code
        == 404
    )


# ------------------------------------------------- мастер: запись и расчёт
def test_walk_in_by_service_and_foreign_service_is_404(
    auth, master_user, point, second_point, service, free_slot
):
    point.posts_count = 2  # второй запрос не должен упереться в занятое время
    point.save(update_fields=["posts_count"])
    payload = {
        "phone": "8 900 555 77 88",
        "full_name": "Сергей",
        "service_point": str(point.pk),
        "service": str(service.pk),
        "start_at": free_slot.start_at.isoformat(),
    }
    api = auth(master_user)

    ok = api.post(master_url("master-booking-list"), payload, format="json")
    assert ok.status_code == 201, ok.content
    assert ok.json()["services"][0]["title"] == service.name

    # Услуга чужой точки при записи на эту — «нет такой», а не чужая цена.
    foreign = ServiceCategory.objects.create(service_point=second_point, name="Чужая")
    other = Service.objects.create(category=foreign, name="Чужая услуга", price=Decimal("1"))
    bad = api.post(
        master_url("master-booking-list"),
        {**payload, "phone": "8 900 555 77 99", "service": str(other.pk)},
        format="json",
    )
    assert bad.status_code == 404
    assert bad.json()["error"]["code"] == "service_not_available"


def test_walk_in_needs_service_or_oil(auth, master_user, point, free_slot):
    resp = auth(master_user).post(
        master_url("master-booking-list"),
        {
            "phone": "8 900 555 77 88",
            "full_name": "С",
            "service_point": str(point.pk),
            "start_at": free_slot.start_at.isoformat(),
        },
        format="json",
    )
    assert resp.status_code == 400


def test_set_service_is_idempotent_and_refused_after_completion(
    auth, master_user, booking, service
):
    api = auth(master_user)
    same = api.post(
        master_url("master-booking-set-service", booking.pk),
        {"service": str(service.pk)},
        format="json",
    )
    assert same.status_code == 200
    assert booking.items.count() == 1  # не задвоилась и не «разобрали» самой же записью

    api.post(master_url("master-booking-complete", booking.pk), {}, format="json")
    late = api.post(
        master_url("master-booking-set-service", booking.pk),
        {"service": str(service.pk)},
        format="json",
    )
    assert late.status_code == 409
    assert late.json()["error"]["code"] == "booking_final"


def test_service_change_rewrites_items_snapshot_and_history(auth, master_user, booking, category):
    other = Service.objects.create(
        category=category,
        name="Mobil 5W-40",
        price=Decimal("4300"),
        material_price=Decimal("3500"),
        is_limited=True,
        quantity=2,
    )

    resp = auth(master_user).post(
        master_url("master-booking-set-service", booking.pk),
        {"service": str(other.pk)},
        format="json",
    )

    assert resp.status_code == 200, resp.content
    booking.refresh_from_db()
    assert [i.service_id for i in booking.items.all()] == [other.pk]
    assert (booking.total_price, booking.material_price, booking.work_price) == (
        Decimal("4300.00"),
        Decimal("3500.00"),
        Decimal("800.00"),
    )
    assert booking.status_logs.filter(comment__contains="Mobil 5W-40").exists()


# ------------------------------------------------------------- дневник
def test_wash_does_not_count_as_oil_change(
    auth, master_user, client_user, client_car, point, wash, free_slot
):
    """Мойка попадает в дневник мойкой и напоминание о масле не двигает."""
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_category(client_user, draft.pk, wash.category_id)
    draft_service.select_service(client_user, draft.pk, wash.pk)
    draft_service.select_slot(client_user, draft.pk, free_slot.start_at)
    made = draft_service.confirm(client_user, draft.pk)
    booking_service.complete(master_user, made.pk)

    rows = journal.items(client_car)

    assert [(r.kind, r.note.split(" · ")[0]) for r in rows] == [("wash", "Мойка кузова")]
    assert not [r for r in rows if r.kind == "oil"]


def test_oil_category_still_counts_as_oil_change(master_user, booking, client_car):
    booking_service.complete(master_user, booking.pk)

    assert [r.kind for r in journal.items(client_car)] == ["oil"]


# ------------------------------------------------------------- старое API
def test_deprecated_oil_endpoints_are_marked_in_schema():
    from drf_spectacular.generators import SchemaGenerator

    paths = SchemaGenerator().get_schema(request=None, public=True)["paths"]

    assert paths["/api/v1/service-points/{point_id}/oils/"]["get"]["deprecated"] is True
    assert paths["/api/v1/master/oils/"]["get"]["deprecated"] is True
    assert paths["/api/v1/bookings/drafts/{id}/select-oil/"]["post"]["deprecated"] is True
    assert "deprecated" not in paths["/api/v1/service-points/{point_id}/categories/"]["get"]


def test_booking_model_reads_unchanged_for_existing_rows(booking):
    """Старые поля заполнены и у записи нового кода: откат кода её прочитает."""
    fresh = Booking.objects.get(pk=booking.pk)

    assert fresh.oil_id is not None
    assert fresh.oil_title == fresh.service_title
