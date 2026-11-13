"""Прямое рабочее место: сохраняемые заказы, резерв баллов и этапы ККТ.

Сервер не выдаёт кассовый чек: он хранит результаты оборудования 1С.
Повтор запроса с тем же checkout_id не повторяет списание баллов.
"""

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.booking.constants import ACTIVE_BOOKING_STATUSES
from apps.booking.models import Booking
from apps.booking.services import booking as booking_service
from apps.common.exceptions import ConflictError, NotFoundError, ValidationError
from apps.onec.models import WorkplaceOrder
from apps.referral.models import ReferralNode
from apps.referral.services import points as points_service

S = WorkplaceOrder.State
HOLD_STATES = (S.PREPARED, S.ACQUIRING, S.ACQUIRED, S.FISCALIZING, S.REVIEW)
CENT = Decimal("0.01")


def held_points(user_id):
    return WorkplaceOrder.objects.filter(booking__user_id=user_id, state__in=HOLD_STATES).aggregate(
        total=Sum("points")
    )["total"] or Decimal(0)


def require_editable(booking):
    if WorkplaceOrder.objects.filter(booking=booking, state__in=HOLD_STATES).exists():
        raise ConflictError(
            "По записи начат расчёт в 1С. Завершите или отмените его в рабочем месте.",
            code="onec_checkout_pending",
        )


def _locked_booking(user, booking_id):
    visible = booking_service.get_for_master(user, booking_id)
    return Booking.objects.select_for_update().get(pk=visible.pk)


def _order_for(booking):
    try:
        return WorkplaceOrder.objects.select_for_update().get(booking=booking)
    except WorkplaceOrder.DoesNotExist as exc:
        raise NotFoundError("Сначала сохраните заказ", code="onec_order_missing") from exc


def _version(order, expected):
    if order.revision != expected:
        raise ConflictError(
            "Заказ изменён в другом окне. Обновите данные перед сохранением.",
            code="onec_revision_conflict",
            details={"revision": order.revision},
        )


def _event(order, name, user):
    order.events = [
        *order.events,
        {"event": name, "at": timezone.now().isoformat(), "actor": str(user.pk)},
    ]
    order.revision += 1
    order.save()


def snapshot(order):
    return {
        "id": str(order.pk),
        "booking_id": str(order.booking_id),
        "revision": order.revision,
        "state": order.state,
        "order_ref": str(order.order_ref) if order.order_ref else None,
        "order_number": order.order_number,
        "lines": order.lines,
        "recommendations": order.recommendations,
        **{key: str(getattr(order, key)) for key in ("total", "points", "cash", "card")},
        "checkout_id": str(order.checkout_id) if order.checkout_id else None,
        "bank_reference": order.bank_reference,
        "receipt": order.receipt,
    }


def get(user, booking_id):
    booking = booking_service.get_for_master(user, booking_id)
    order = WorkplaceOrder.objects.filter(booking=booking).first()
    return snapshot(order) if order else None


def quote(user, booking_id, *, total):
    booking = booking_service.get_for_master(user, booking_id)
    booking.final_price = total
    result = points_service.spend_quote(booking)
    return {
        key: str(value) if isinstance(value, Decimal) else value for key, value in result.items()
    }


@transaction.atomic
def save(user, booking_id, *, revision, lines, recommendations="", order_ref=None, order_number=""):
    booking = _locked_booking(user, booking_id)
    if booking.status not in ACTIVE_BOOKING_STATUSES:
        raise ConflictError("Запись уже завершена", code="booking_final")
    order, _ = WorkplaceOrder.objects.get_or_create(booking=booking)
    _version(order, revision)
    if order.state != S.DRAFT:
        raise ConflictError("Состав расчёта уже зафиксирован", code="onec_checkout_pending")
    amounts = [
        line.get(
            "amount",
            (Decimal(line["quantity"]) * Decimal(line["price"])).quantize(
                CENT, rounding=ROUND_HALF_UP
            ),
        )
        for line in lines
    ]
    total = sum(amounts)
    if total <= 0:
        raise ValidationError("Добавьте работы и материалы с положительным итогом")
    # Сохраняем десятичные числа строками: JSON float теряет копейки.
    if total > Decimal("99999999.99"):
        raise ValidationError("Превышена допустимая сумма заказа")
    order.lines = [
        {
            **{
                key: str(value) if isinstance(value, Decimal | UUID) else value
                for key, value in line.items()
            },
            "amount": str(amount),
        }
        for line, amount in zip(lines, amounts, strict=True)
    ]
    order.total = total
    order.recommendations = recommendations
    order.order_ref, order.order_number = order_ref, order_number
    _event(order, "saved", user)
    return snapshot(order)


@transaction.atomic
def prepare(user, booking_id, *, revision, points, cash, card, checkout_id):
    booking = _locked_booking(user, booking_id)
    order = _order_for(booking)
    if order.checkout_id == checkout_id and order.state != S.DRAFT:
        if (order.points, order.cash, order.card) != (points, cash, card):
            raise ConflictError(
                "Идентификатор расчёта уже использован", code="onec_checkout_conflict"
            )
        return snapshot(order)
    _version(order, revision)
    if WorkplaceOrder.objects.exclude(pk=order.pk).filter(checkout_id=checkout_id).exists():
        raise ConflictError("Идентификатор расчёта уже использован", code="onec_checkout_conflict")
    if order.state != S.DRAFT or booking.status not in ACTIVE_BOOKING_STATUSES:
        raise ConflictError("Расчёт уже начат или запись завершена", code="onec_checkout_pending")
    if not booking.items.exists():
        raise ValidationError("Сначала выберите услугу записи", code="service_required")
    if points + cash + card != order.total:
        raise ValidationError("Баллы, наличные и карта должны составлять итог заказа")
    booking.final_price = order.total
    if points > points_service.max_discount(booking):
        raise ConflictError("Превышен лимит списания баллов", code="points_limit_exceeded")
    node = ReferralNode.objects.select_for_update().filter(user_id=booking.user_id).first()
    available = (node.balance if node else Decimal(0)) - held_points(booking.user_id)
    if points > available:
        raise ConflictError("Недостаточно свободных баллов", code="not_enough_points")
    order.points, order.cash, order.card = points, cash, card
    order.checkout_id, order.state = checkout_id, S.PREPARED
    order.bank_reference, order.receipt = "", {}
    _event(order, "prepared", user)
    return snapshot(order)


@transaction.atomic
def advance(user, booking_id, *, checkout_id, event, bank_reference="", receipt=None):
    booking = _locked_booking(user, booking_id)
    order = _order_for(booking)
    if order.checkout_id != checkout_id:
        raise ConflictError("Другой идентификатор расчёта", code="onec_checkout_conflict")
    # Сначала проверка повтора: ответ мог потеряться после успешного COMMIT.
    if order.state == S.COMPLETED:
        if event == "fiscal_succeeded" and order.receipt == receipt:
            return snapshot(order)
        raise ConflictError("Расчёт уже завершён", code="onec_checkout_completed")
    transitions = {
        "card_started": ((S.PREPARED,), S.ACQUIRING),
        "card_succeeded": ((S.ACQUIRING,), S.ACQUIRED),
        "card_declined": ((S.ACQUIRING,), S.PREPARED),
        "cash_confirmed": ((S.PREPARED,), S.ACQUIRED),
        "fiscal_started": ((S.ACQUIRED,), S.FISCALIZING),
        "fiscal_succeeded": ((S.FISCALIZING,), S.COMPLETED),
        "review": (HOLD_STATES, S.REVIEW),
        "cancel": ((S.PREPARED,), S.DRAFT),
    }
    allowed, target = transitions[event]
    if (
        order.state == target
        and event not in ("cancel", "card_declined")
        and (event != "card_succeeded" or order.bank_reference == bank_reference)
    ):
        return snapshot(order)
    if order.state not in allowed:
        raise ConflictError("Недопустимый этап расчёта", code="onec_checkout_state")
    if event == "card_started" and order.card <= 0:
        raise ValidationError("В этом расчёте нет оплаты картой")
    if event == "cash_confirmed" and (order.card > 0 or order.cash <= 0):
        raise ValidationError("Для этого расчёта требуется подтверждение терминала")
    if event == "card_succeeded":
        if not bank_reference:
            raise ValidationError("Нужен идентификатор подтверждённой банковской операции")
        order.bank_reference = bank_reference
    if event == "fiscal_succeeded":
        if not receipt or not receipt.get("number"):
            raise ValidationError("Нужны реквизиты фискального чека")
        order.receipt = receipt
    order.state = target
    if event == "cancel":
        order.points = order.cash = order.card = Decimal(0)
        order.checkout_id = None
    _event(order, event, user)
    if event == "fiscal_succeeded":
        # Резерв собственного заказа уже снят внутри той же транзакции.
        # Списание, завершение записи и реферальные начисления — штатным сервисом.
        booking_service.complete(
            user,
            booking.pk,
            points=order.points,
            final_price=order.total,
            reason=f"Расчёт в 1С, заказ {order.order_number}",
        )
    result = snapshot(order)
    if event in ("card_started", "fiscal_started"):
        # Только первый подтверждённый запрос разрешает вызов оборудования.
        # Повтор после потери ответа не должен снова списывать деньги/печатать чек.
        result["dispatch"] = True
    return result
