"""Баллы: поступления в плечи, ночное сведение и списание при расчёте.

Жизненный цикл балла:

1. **Поступление в плечо.** Мастер отметил запись выполненной — её чек
   (заплаченное деньгами) превращается в баллы для трёх вышестоящих по
   ставкам линий. Баллы ложатся не на баланс, а в плечо вышестоящего —
   левое или правое, смотря в какой ветке стоит покупатель (`LegCredit`).
   Вызов стоит внутри той же транзакции, что и завершение записи.

2. **Сведение.** Раз в сутки, в полночь по Челябинску, плечи каждого
   участника сводятся (`settle_due_days`):
   - одно из плеч пустое — выплаты нет, всё переносится;
   - плечи равны — выплачиваются оба, плечи обнуляются;
   - иначе выплачивается меньшее плечо, оно обнуляется, а излишек
     сильного переносится на следующие сутки.
   Выплата — строка журнала `PAYOUT` и прибавка к балансу.

3. **Списание.** При завершении записи клиент может закрыть баллами часть
   чека, не больше `MAX_DISCOUNT_PERCENT` (`spend`).
"""

from __future__ import annotations

import logging
import zoneinfo
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Min, Sum
from django.utils import timezone

from apps.common.exceptions import ConflictError, ValidationError
from apps.referral.constants import MatrixPosition, PointsKind
from apps.referral.models import BinarySettlement, LegCredit, PointsEntry, ReferralNode
from apps.referral.services import tree

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _round(value: Decimal) -> Decimal:
    """Округление до копейки, как в кассовом чеке."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------ поступления
def base_amount(booking) -> Decimal:
    """С какой суммы считать баллы.

    `total` — сколько клиент заплатил деньгами: часть чека, закрытая
    баллами, новых баллов не рождает, иначе баллы воспроизводили бы сами
    себя. `work` — только работа: масло перепродаётся с почти постоянной
    наценкой, и дорогая канистра увеличивала бы выплату, не увеличивая
    заработок сервиса.
    """
    if settings.REFERRAL["BASE"] == "work":
        return Decimal(booking.work_price)
    return Decimal(booking.total_price) - Decimal(booking.points_spent or 0)


@transaction.atomic
def credit_legs_for_booking(booking) -> list[LegCredit]:
    """Разложить баллы с выполненной записи по плечам вышестоящих.

    Поднимаемся от покупателя по `parent`: на каждом шаге вышестоящий
    получает баллы в то плечо, в котором стоит узел, из которого мы к нему
    поднялись. Повторный вызов дублей не создаёт — это держит уникальный
    индекс `uniq_credit_per_booking_node`.
    """
    config = settings.REFERRAL
    if not config["ENABLED"] or not config["LEVEL_PERCENTS"]:
        return []

    buyer = tree.get_node(booking.user)
    if buyer is None:
        return []

    base = base_amount(booking)
    if base <= 0:
        return []

    created: list[LegCredit] = []
    child = buyer
    for level, percent in enumerate(config["LEVEL_PERCENTS"], start=1):
        if child.parent_id is None:
            break
        upline = ReferralNode.objects.get(pk=child.parent_id)
        amount = _round(base * percent / Decimal(100))
        if amount > 0:
            try:
                with transaction.atomic():
                    created.append(
                        LegCredit.objects.create(
                            node=upline,
                            side=child.position,
                            amount=amount,
                            booking=booking,
                            source_node=buyer,
                            level=level,
                            percent=percent,
                            base_amount=base,
                        )
                    )
            except IntegrityError:
                # Уже раскладывали эту запись — повторное «Выполнено».
                pass
        child = upline
    return created


# ------------------------------------------------------------- сведение
def payout_tz() -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(settings.REFERRAL["PAYOUT_TIMEZONE"])


def day_end(day: date) -> datetime:
    """Конец суток `day` по времени выплат — полночь следующих суток."""
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=payout_tz())


def next_payout_at(now: datetime | None = None) -> datetime:
    """Ближайшая полночь по времени выплат."""
    local = (now or timezone.now()).astimezone(payout_tz())
    return day_end(local.date())


def split_payout(left: Decimal, right: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Правило выплаты. Возвращает (выплата, остаток слева, остаток справа).

    Одно плечо пустое — выплаты нет. Равны — выплачиваются оба. Иначе —
    меньшее, а сильное уменьшается на него же: излишек ждёт следующих суток.
    """
    if left <= 0 or right <= 0:
        return ZERO, left, right
    if left == right:
        return left + right, ZERO, ZERO
    weak = min(left, right)
    return weak, left - weak, right - weak


@transaction.atomic
def _settle_node(node_id, day: date, credits: list[LegCredit]) -> BinarySettlement | None:
    """Свести плечи одного участника за одни сутки."""
    node = ReferralNode.objects.select_for_update().get(pk=node_id)
    if BinarySettlement.objects.filter(node=node, day=day).exists():
        # Эти сутки уже сведены (параллельный или повторный запуск).
        return None

    added = {MatrixPosition.LEFT: ZERO, MatrixPosition.RIGHT: ZERO}
    for credit in credits:
        added[credit.side] += credit.amount

    left_before, right_before = node.carry_left, node.carry_right
    paid, left_after, right_after = split_payout(
        left_before + added[MatrixPosition.LEFT],
        right_before + added[MatrixPosition.RIGHT],
    )

    entry = None
    if paid > 0:
        entry = PointsEntry.objects.create(
            node=node,
            amount=paid,
            kind=PointsKind.PAYOUT,
            comment=(
                f"Выплата за {day:%d.%m.%Y}: слева "
                f"{left_before + added[MatrixPosition.LEFT]}, справа "
                f"{right_before + added[MatrixPosition.RIGHT]}"
            ),
        )

    settlement = BinarySettlement.objects.create(
        node=node,
        day=day,
        left_before=left_before,
        right_before=right_before,
        left_added=added[MatrixPosition.LEFT],
        right_added=added[MatrixPosition.RIGHT],
        paid=paid,
        left_after=left_after,
        right_after=right_after,
        entry=entry,
    )
    LegCredit.objects.filter(pk__in=[c.pk for c in credits]).update(settlement=settlement)
    ReferralNode.objects.filter(pk=node.pk).update(
        carry_left=left_after,
        carry_right=right_after,
        balance=F("balance") + paid,
    )
    return settlement


def settle_day(day: date) -> int:
    """Свести все поступления, пришедшие до конца суток `day`.

    Сутки сводятся по одному участнику за транзакцию: ночная задача по всей
    базе в одной транзакции держала бы блокировки на всех узлах сразу.
    """
    boundary = day_end(day)
    pending = LegCredit.objects.filter(settlement__isnull=True, created_at__lt=boundary)
    by_node: dict = defaultdict(list)
    for credit in pending.only("id", "node_id", "side", "amount"):
        by_node[credit.node_id].append(credit)

    settled = 0
    for node_id, credits in by_node.items():
        if _settle_node(node_id, day, credits) is not None:
            settled += 1
    return settled


def settle_due_days(now: datetime | None = None) -> int:
    """Свести все сутки, которые уже закончились, по порядку.

    Порядок важен: при переносе остатка три дня, сведённые по одному, и
    те же дни, слитые в один, дают разные выплаты. Поэтому пропущенные
    ночи (воркер лежал) догоняются каждая отдельно.
    """
    today = (now or timezone.now()).astimezone(payout_tz()).date()
    first = LegCredit.objects.filter(settlement__isnull=True).aggregate(
        first=Min("created_at")
    )["first"]
    if first is None:
        return 0

    settled = 0
    day = first.astimezone(payout_tz()).date()
    while day < today:
        settled += settle_day(day)
        day += timedelta(days=1)
    if settled:
        logger.info("Сведено плеч: %s", settled)
    return settled


def pending_legs(node: ReferralNode) -> tuple[Decimal, Decimal]:
    """Что лежит в плечах прямо сейчас: перенос плюс несведённое за сегодня."""
    rows = (
        LegCredit.objects.filter(node=node, settlement__isnull=True)
        .values("side")
        .annotate(total=Sum("amount"))
    )
    fresh = {row["side"]: row["total"] for row in rows}
    return (
        node.carry_left + fresh.get(MatrixPosition.LEFT, ZERO),
        node.carry_right + fresh.get(MatrixPosition.RIGHT, ZERO),
    )


# ------------------------------------------------------------- списание
def max_discount(booking) -> Decimal:
    """Потолок оплаты баллами для этого чека.

    Баллы — скидка, а не вторая касса: работа мастера и масло по
    себестоимости должны быть оплачены деньгами.
    """
    percent = Decimal(settings.REFERRAL["MAX_DISCOUNT_PERCENT"])
    return _round(Decimal(booking.total_price) * percent / Decimal(100))


def _already_spent(booking) -> Decimal:
    total = PointsEntry.objects.filter(booking=booking, kind=PointsKind.SPEND).aggregate(
        total=Sum("amount")
    )["total"]
    return -(total or ZERO)


def spend_quote(booking) -> dict:
    """Что показать мастеру в окне расчёта: баланс клиента и сколько можно списать."""
    node = tree.get_node(booking.user)
    balance = node.balance if node else ZERO
    limit = max(max_discount(booking) - _already_spent(booking), ZERO)
    return {
        "balance": balance,
        "limit": limit,
        "max_spend": min(balance, limit),
        "total_price": booking.total_price,
        "max_discount_percent": settings.REFERRAL["MAX_DISCOUNT_PERCENT"],
    }


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
        # Потолок — на чек целиком, а не на одно списание: иначе два
        # списания по 50 % закрывают запись баллами полностью. Уже
        # списанное читаем после блокировки узла — параллельное списание
        # по той же записи ждёт на ней же и увидит наше.
        limit = max_discount(booking) - _already_spent(booking)
        if amount > limit:
            raise ConflictError(
                "Баллами можно закрыть только часть чека",
                code="points_limit_exceeded",
                details={"limit": str(max(limit, ZERO))},
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
