"""Ручная сверка неизвестного результата по журналу терминала/ККТ.

Не вызывает оборудование. Доступна администратору через management-команду.
"""

from django.db import transaction
from django.utils import timezone

from apps.accounts.constants import UserRole
from apps.common.exceptions import ConflictError, PermissionError_, ValidationError
from apps.onec.services import workplace


@transaction.atomic
def reconcile(
    user, booking_id, *, checkout_id, revision, outcome, evidence, bank_reference="", receipt=None
):
    if not user.is_active or user.role != UserRole.ADMIN:
        raise PermissionError_("Сверку выполняет администратор")
    if not evidence.strip() or len(evidence) > 2000:
        raise ValidationError("Укажите результат проверки журнала терминала/ККТ (до 2000 знаков)")
    booking = workplace._locked_booking(user, booking_id)
    order = workplace._order_for(booking)
    workplace._version(order, revision)
    if order.checkout_id != checkout_id:
        raise ConflictError("Другой идентификатор расчёта")
    state = workplace.S
    if order.state not in (state.ACQUIRING, state.FISCALIZING, state.REVIEW):
        raise ConflictError("На этом этапе ручная сверка не требуется")
    previous = order.state
    if outcome == "not-charged":
        if order.card <= 0 or order.bank_reference or previous == state.FISCALIZING:
            raise ConflictError("Есть подтверждённая оплата; нужен возврат или сверка чека")
        order.state = state.PREPARED
    elif outcome == "bank-confirmed":
        if order.card <= 0 or not bank_reference or len(bank_reference) > 128:
            raise ValidationError("Укажите подтверждённый RRN операции")
        if order.bank_reference and order.bank_reference != bank_reference:
            raise ConflictError("В расчёте уже записан другой RRN")
        order.bank_reference, order.state = bank_reference, state.ACQUIRED
    elif outcome in ("no-receipt", "receipt"):
        if order.card > 0 and not order.bank_reference:
            raise ConflictError("Сначала подтвердите банковскую операцию")
        if outcome == "receipt" and (not receipt or not receipt.get("number")):
            raise ValidationError("Нужны реквизиты реально зарегистрированного чека")
        order.state = state.FISCALIZING if outcome == "receipt" else state.ACQUIRED
    else:
        raise ValidationError("Неизвестный результат сверки")
    order.events = [
        *order.events,
        {
            "event": "reconciled",
            "at": timezone.now().isoformat(),
            "actor": str(user.pk),
            "from_state": previous,
            "outcome": outcome,
            "evidence": evidence.strip(),
        },
    ]
    order.revision += 1
    order.save()
    if outcome == "receipt":
        return workplace.advance(
            user, booking.pk, checkout_id=checkout_id, event="fiscal_succeeded", receipt=receipt
        )
    return workplace.snapshot(order)
