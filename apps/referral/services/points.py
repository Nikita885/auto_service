"""Начисление и списание баллов.

Начисляем ровно в момент, когда работы признаны выполненными: до этого
деньги не получены, а запись ещё можно отменить. Поэтому вызов стоит в
`booking.services.booking.complete()` рядом со списанием канистры и внутри
той же транзакции — баллы и выполненная работа либо появляются вместе,
либо не появляются вовсе.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F

from apps.common.exceptions import ConflictError, ValidationError
from apps.referral.constants import PointsKind
from apps.referral.models import PointsEntry, ReferralNode
from apps.referral.services import tree

CENT = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    """Округление до копейки в пользу участника, как в кассовом чеке."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def base_amount(booking) -> Decimal:
    """С какой части чека считаем процент.

    `work` — только работа. Масло перепродаётся с почти фиксированной
    наценкой, а чек скачет в зависимости от того, какое масло выбрали: при
    расчёте от полного чека дорогое масло увеличивает выплату, не увеличивая
    заработок сервиса.
    """
    if settings.REFERRAL["BASE"] == "work":
        return Decimal(booking.work_price)
    return Decimal(booking.total_price)


@transaction.atomic
def accrue_for_booking(booking) -> list[PointsEntry]:
    """Начислить баллы вышестоящим за выполненную запись.

    Возвращает созданные движения. Повторный вызов не создаёт дублей:
    уникальный индекс `uniq_accrual_per_booking_node` не даст начислить
    одному и тому же человеку за одну и ту же запись дважды.
    """
    config = settings.REFERRAL
    if not config["ENABLED"]:
        return []

    percents = config["LEVEL_PERCENTS"]
    if not percents:
        return []

    node = tree.get_node(booking.user)
    if node is None:
        return []

    base = base_amount(booking)
    if base <= 0:
        return []

    created: list[PointsEntry] = []
    for level, upline_node in enumerate(tree.upline(node, len(percents)), start=1):
        percent = percents[level - 1]
        if percent <= 0:
            continue

        amount = _round(base * percent / Decimal(100))
        if amount <= 0:
            continue

        try:
            with transaction.atomic():
                entry = PointsEntry.objects.create(
                    node=upline_node,
                    amount=amount,
                    kind=PointsKind.ACCRUAL,
                    booking=booking,
                    source_node=node,
                    level=level,
                    percent=percent,
                    base_amount=base,
                    comment=f"{level}-я линия с записи {booking.code}",
                )
        except IntegrityError:
            # Уже начисляли за эту запись — значит `complete()` провели
            # повторно. Молча пропускаем: это не ошибка оператора.
            continue

        ReferralNode.objects.filter(pk=upline_node.pk).update(
            balance=F("balance") + amount
        )
        created.append(entry)

    return created


@transaction.atomic
def spend(node: ReferralNode, amount: Decimal, *, booking=None, comment: str = "") -> PointsEntry:
    """Списать баллы в счёт оплаты.

    Баланс перечитывается под блокировкой строки: два списания подряд с
    разных экранов иначе могли бы увести баланс в минус.
    """
    amount = _round(Decimal(amount))
    if amount <= 0:
        raise ValidationError("Сумма списания должна быть больше нуля", code="invalid_amount")

    locked = ReferralNode.objects.select_for_update().get(pk=node.pk)
    if locked.balance < amount:
        raise ConflictError(
            "Недостаточно баллов",
            code="not_enough_points",
            details={"balance": str(locked.balance), "requested": str(amount)},
        )

    if booking is not None:
        limit = max_discount(booking)
        if amount > limit:
            raise ConflictError(
                "Баллами можно закрыть только часть чека",
                code="points_limit_exceeded",
                details={"limit": str(limit)},
            )

    entry = PointsEntry.objects.create(
        node=locked,
        amount=-amount,
        kind=PointsKind.SPEND,
        booking=booking,
        comment=comment or (f"Оплата записи {booking.code}" if booking else ""),
    )
    ReferralNode.objects.filter(pk=locked.pk).update(balance=F("balance") - amount)
    return entry


def max_discount(booking) -> Decimal:
    """Сколько баллов разрешено списать в этот чек.

    Потолок нужен, чтобы замена не уходила в ноль: баллы — скидка, а не
    вторая касса, и работа мастера должна быть оплачена деньгами.
    """
    percent = Decimal(settings.REFERRAL["MAX_DISCOUNT_PERCENT"])
    return _round(Decimal(booking.total_price) * percent / Decimal(100))
