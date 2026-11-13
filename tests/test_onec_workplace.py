from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import reverse

from apps.booking.constants import BookingStatus
from apps.booking.serializers import BookingSerializer
from apps.booking.services import booking as booking_service
from apps.common.exceptions import ConflictError
from apps.onec.models import WorkplaceOrder
from apps.referral.constants import PointsKind
from apps.referral.models import PointsEntry
from apps.referral.services import points as points_service

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def desk(api, master_user):
    api.force_authenticate(master_user)
    return api


def endpoint(name, booking):
    return reverse("v1:onec:workplace-" + name, args=[booking.pk])


def save(desk, booking, revision=1):
    return desk.post(
        endpoint("order", booking),
        {
            "revision": revision,
            "order_ref": str(uuid4()),
            "order_number": "АС-127",
            "lines": [
                {
                    "ref": str(uuid4()),
                    "kind": "work",
                    "name": "Замена масла",
                    "unit": "усл.",
                    "quantity": "1",
                    "price": "800",
                },
                {
                    "kind": "material",
                    "name": "Масло 5W-30",
                    "unit": "л",
                    "quantity": "4.3",
                    "price": "950",
                },
            ],
            "recommendations": "Проверить фильтр",
        },
        format="json",
    )


def prepare(desk, booking, *, points="0", cash="0", card=None, checkout_id=None):
    order = WorkplaceOrder.objects.get(booking=booking)
    return desk.post(
        endpoint("prepare", booking),
        {
            "revision": order.revision,
            "checkout_id": str(checkout_id or uuid4()),
            "points": points,
            "cash": cash,
            "card": card
            if card is not None
            else str(order.total - Decimal(points) - Decimal(cash)),
        },
        format="json",
    )


def event(desk, booking, name, **extra):
    order = WorkplaceOrder.objects.get(booking=booking)
    return desk.post(
        endpoint("event", booking),
        {
            "checkout_id": str(order.checkout_id),
            "event": name,
            **extra,
        },
        format="json",
    )


def test_direct_access_requires_staff(api, booking, client_user):
    assert api.get(endpoint("order", booking)).status_code == 401
    api.force_authenticate(client_user)
    assert api.get(endpoint("order", booking)).status_code == 403


def test_other_point_is_not_accessible(desk, master_user, second_point, booking):
    master_user.service_points.set([second_point])
    assert desk.get(endpoint("order", booking)).status_code == 403
    assert not WorkplaceOrder.objects.exists()


def test_decimal_lines_saved_and_version_protected(desk, booking):
    response = save(desk, booking)
    assert response.status_code == 200, response.data
    order = response.data["order"]
    assert Decimal(order["total"]) == Decimal("4885.00")
    assert Decimal(order["lines"][1]["quantity"]) == Decimal("4.3")
    assert save(desk, booking).status_code == 409
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert BookingSerializer(booking).data["service_report"] is None


def test_unknown_order_returns_domain_error(desk, booking):
    response = desk.post(
        endpoint("prepare", booking),
        {
            "revision": 1,
            "checkout_id": str(uuid4()),
            "points": 0,
            "cash": 0,
            "card": 1,
        },
        format="json",
    )
    assert response.status_code == 404
    assert response.data["error"]["code"] == "onec_order_missing"


def test_prepare_reserves_points_without_spending(desk, booking, client_points):
    node = client_points("2000")
    save(desk, booking)
    result = prepare(desk, booking, points="1000", cash="500")
    assert result.status_code == 200, result.data
    node.refresh_from_db()
    assert node.balance == Decimal("2000")
    assert points_service.spend_quote(booking)["balance"] == Decimal("1000")
    with pytest.raises(ConflictError, match="Недостаточно"):
        points_service.spend(node, Decimal("1500"))
    assert not PointsEntry.objects.filter(kind=PointsKind.SPEND).exists()


def test_checkout_freezes_booking_edits_and_other_completion(desk, booking, master_user):
    save(desk, booking)
    prepare(desk, booking)
    with pytest.raises(ConflictError) as exc:
        booking_service.edit_by_master(master_user, booking.pk, comment="Звонок")
    assert exc.value.code == "onec_checkout_pending"
    with pytest.raises(ConflictError):
        booking_service.complete(master_user, booking.pk)


def test_prepare_checks_split_and_points_cap(desk, booking, client_points):
    client_points("10000")
    save(desk, booking)
    assert prepare(desk, booking, cash="1", card="1").status_code == 400
    assert prepare(desk, booking, points="3000").status_code == 409
    assert WorkplaceOrder.objects.get(booking=booking).state == "draft"


def test_prepare_retry_does_not_hold_twice(desk, booking, client_points):
    client_points("2000")
    save(desk, booking)
    checkout_id = uuid4()
    first = prepare(desk, booking, points="500", checkout_id=checkout_id)
    second = prepare(desk, booking, points="500", checkout_id=checkout_id)
    assert first.data == second.data
    assert points_service.spend_quote(booking)["balance"] == Decimal("1500")


def test_equipment_dispatch_is_granted_once(desk, booking):
    save(desk, booking)
    prepare(desk, booking)
    first = event(desk, booking, "card_started")
    assert first.data["order"]["dispatch"] is True
    retry = event(desk, booking, "card_started")
    assert "dispatch" not in retry.data["order"]
    assert event(desk, booking, "fiscal_started").status_code == 409


def test_unknown_terminal_result_cannot_be_cancelled_or_retried(desk, booking, client_points):
    client_points("2000")
    save(desk, booking)
    prepare(desk, booking, points="500")
    event(desk, booking, "card_started")
    event(desk, booking, "review")
    assert event(desk, booking, "cancel").status_code == 409
    assert event(desk, booking, "card_started").status_code == 409
    assert points_service.spend_quote(booking)["balance"] == Decimal("1500")


def test_unstarted_checkout_can_be_cancelled_and_points_released(desk, booking, client_points):
    client_points("2000")
    save(desk, booking)
    prepare(desk, booking, points="500")
    assert event(desk, booking, "cancel").status_code == 200
    assert points_service.spend_quote(booking)["balance"] == Decimal("2000")


def test_mixed_payment_receipt_completes_once_with_report(desk, booking, client_points):
    node = client_points("2000")
    save(desk, booking)
    prepare(desk, booking, points="1000", cash="500")
    event(desk, booking, "card_started")
    assert event(desk, booking, "card_succeeded", bank_reference="RRN-123").status_code == 200
    assert event(desk, booking, "fiscal_started").data["order"]["dispatch"] is True
    assert "dispatch" not in event(desk, booking, "fiscal_started").data["order"]
    receipt = {"number": "127", "shift": "5"}
    response = event(desk, booking, "fiscal_succeeded", receipt=receipt)
    assert response.status_code == 200, response.data
    assert event(desk, booking, "fiscal_succeeded", receipt=receipt).status_code == 200
    node.refresh_from_db()
    booking.refresh_from_db()
    assert node.balance == Decimal("1000")
    assert booking.points_spent == Decimal("1000")
    assert booking.status == BookingStatus.COMPLETED
    assert booking.paid_amount == Decimal("3885")
    assert PointsEntry.objects.filter(booking=booking, kind=PointsKind.SPEND).count() == 1
    report = BookingSerializer(booking).data["service_report"]
    assert len(report["lines"]) == 2
    assert report["recommendations"] == "Проверить фильтр"
    assert report["receipt"] == receipt
    assert "ref" not in report["lines"][0]


def test_cash_payment_needs_no_acquiring(desk, booking):
    save(desk, booking)
    assert prepare(desk, booking, cash="4885", card="0").status_code == 200
    assert event(desk, booking, "card_started").status_code == 400
    assert event(desk, booking, "cash_confirmed").status_code == 200
    assert event(desk, booking, "fiscal_started").status_code == 200
    assert event(desk, booking, "fiscal_succeeded", receipt={"number": "1"}).status_code == 200


def test_car_vin_mileage_and_stale_version(desk, booking):
    response = desk.post(
        reverse("v1:master:master-booking-edit", args=[booking.pk]),
        {
            "expected_version": booking.updated_at.isoformat(),
            "car_vin": "XTA210990Y2761123",
            "car_mileage": 87000,
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["car_vin"] == "XTA210990Y2761123"
    assert response.data["car_mileage"] == 87000
    stale = desk.post(
        reverse("v1:master:master-booking-edit", args=[booking.pk]),
        {
            "expected_version": booking.updated_at.isoformat(),
            "comment": "Старое окно",
        },
        format="json",
    )
    assert stale.status_code == 409


def test_native_tax_and_discount_amount_is_preserved(desk, booking):
    response = desk.post(
        endpoint("order", booking),
        {
            "revision": 1,
            "lines": [
                {
                    "kind": "work",
                    "name": "Работа с НДС",
                    "quantity": "1",
                    "price": "100",
                    "amount": "120",
                }
            ],
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert Decimal(response.data["order"]["total"]) == Decimal("120")
    assert response.data["order"]["lines"][0]["amount"] == "120.00"


def test_local_booking_time_uses_point_timezone(desk, booking):
    local = booking.start_at.astimezone(booking.service_point.tz).strftime("%Y-%m-%dT%H:%M")
    response = desk.post(
        reverse("v1:master:master-booking-edit", args=[booking.pk]),
        {"expected_version": booking.updated_at.isoformat(), "start_local": local},
        format="json",
    )
    assert response.status_code == 200, response.data
    booking.refresh_from_db()
    assert booking.start_at.astimezone(booking.service_point.tz).strftime("%Y-%m-%dT%H:%M") == local


def test_cash_cannot_skip_confirmation(desk, booking):
    save(desk, booking)
    prepare(desk, booking, cash="4885", card="0")
    assert event(desk, booking, "fiscal_started").status_code == 409


def test_concurrent_hardware_start_dispatches_once(desk, booking, master_user):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection

    from apps.onec.services import workplace

    if connection.vendor != "postgresql":
        pytest.skip("Проверка блокировок требует PostgreSQL")
    save(desk, booking)
    prepare(desk, booking)
    checkout_id = WorkplaceOrder.objects.get(booking=booking).checkout_id
    barrier = Barrier(2)

    def start():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return workplace.advance(
                master_user, booking.pk, checkout_id=checkout_id, event="card_started"
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: start(), range(2)))
    assert sum(bool(result.get("dispatch")) for result in results) == 1
    assert WorkplaceOrder.objects.get(booking=booking).state == "acquiring"


def test_parallel_orders_cannot_reserve_the_same_points_twice(
    desk, booking, master_user, client_points
):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta
    from threading import Barrier

    from django.db import close_old_connections, connection

    from apps.booking.models import Booking, BookingItem
    from apps.onec.services import workplace

    if connection.vendor != "postgresql":
        pytest.skip("Проверка блокировок требует PostgreSQL")
    client_points("1000")
    fields = {
        f.attname: getattr(booking, f.attname)
        for f in Booking._meta.fields
        if not f.primary_key and f.name not in ("created_at", "updated_at", "code")
    }
    fields["start_at"] += timedelta(hours=1)
    fields["end_at"] += timedelta(hours=1)
    other = Booking.objects.create(**fields)
    for item in booking.items.all():
        values = {
            f.attname: getattr(item, f.attname)
            for f in BookingItem._meta.fields
            if not f.primary_key and f.name not in ("created_at", "updated_at", "booking")
        }
        BookingItem.objects.create(booking=other, **values)
    assert save(desk, booking).status_code == 200
    assert save(desk, other).status_code == 200
    barrier = Barrier(2)

    def reserve(booking_id):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            workplace.prepare(
                master_user,
                booking_id,
                revision=2,
                checkout_id=uuid4(),
                points=Decimal(700),
                cash=Decimal(0),
                card=Decimal(4185),
            )
            return "prepared"
        except ConflictError as exc:
            return exc.code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, [booking.pk, other.pk]))
    assert sorted(results) == ["not_enough_points", "prepared"]
    assert workplace.held_points(booking.user_id) == Decimal(700)
    assert not PointsEntry.objects.filter(kind=PointsKind.SPEND).exists()
