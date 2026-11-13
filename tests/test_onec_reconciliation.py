from uuid import uuid4

import pytest

from apps.accounts.constants import UserRole
from apps.accounts.models import User
from apps.common.exceptions import ConflictError, PermissionError_
from apps.onec.models import WorkplaceOrder
from apps.onec.services.reconciliation import reconcile
from apps.onec.services.workplace import advance

pytestmark = pytest.mark.django_db


@pytest.fixture
def uncertain(booking):
    order = WorkplaceOrder.objects.create(
        booking=booking, state="review", checkout_id=uuid4(), total=100, card=100
    )
    admin = User.objects.create_user(phone="+79000000002", role=UserRole.ADMIN)
    return order, admin


def resolve(order, user, outcome, **kwargs):
    return reconcile(
        user,
        order.booking_id,
        checkout_id=order.checkout_id,
        revision=order.revision,
        outcome=outcome,
        evidence="Сверены журнал терминала и журнал ККТ за смену",
        **kwargs,
    )


def test_master_cannot_unlock_unknown_charge(uncertain, master_user):
    order, _ = uncertain
    with pytest.raises(PermissionError_):
        resolve(order, master_user, "not-charged")


def test_verified_decline_can_resume_once_with_audit(uncertain):
    order, admin = uncertain
    result = resolve(order, admin, "not-charged")
    assert result["state"] == "prepared"
    order.refresh_from_db()
    assert order.events[-1]["actor"] == str(admin.pk)
    assert order.events[-1]["evidence"]
    args = {"checkout_id": order.checkout_id, "event": "card_started"}
    assert advance(admin, order.booking_id, **args)["dispatch"] is True
    assert "dispatch" not in advance(admin, order.booking_id, **args)


def test_bank_confirmation_cannot_be_erased(uncertain):
    order, admin = uncertain
    resolve(order, admin, "bank-confirmed", bank_reference="RRN-777")
    order.refresh_from_db()
    order.state = "review"
    order.save()
    with pytest.raises(ConflictError):
        resolve(order, admin, "not-charged")
    assert resolve(order, admin, "no-receipt")["state"] == "acquired"


def test_receipt_requires_bank_confirmation(uncertain):
    order, admin = uncertain
    with pytest.raises(ConflictError):
        resolve(order, admin, "receipt", receipt={"number": "127"})
    assert WorkplaceOrder.objects.get(pk=order.pk).state == "review"
