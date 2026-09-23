"""Сводка по участнику программы: то, что видит клиент на своём экране.

Отдельный модуль рядом с `tree` и `points`, потому что это другой вопрос.
`tree` отвечает «кто под кем стоит», `points` — «кому сколько начислить», а
здесь собирается ответ на «что показать человеку»: код, ссылка, баланс,
сколько людей пришло и сколько они принесли.

Вьюха только отдаёт этот словарь наружу — никаких подсчётов в HTTP-слое.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db.models import Sum

from apps.common.phone import mask_phone
from apps.referral.constants import PointsKind
from apps.referral.models import LegCredit, PointsEntry, ReferralNode
from apps.referral.services import points as points_service
from apps.referral.services import tree

ZERO = Decimal("0.00")


def invite_url(code: str) -> str:
    """Ссылка-приглашение. Домен берём из настроек, а не из запроса:
    ссылку пересылают в мессенджер, и она обязана вести на канонический
    адрес, а не на тот, с которого её случайно открыли."""
    return f"{settings.COMPANY['SITE_URL']}/i/{code}"


def line_counts(node: ReferralNode, levels: int) -> list[int]:
    """Сколько человек стоит на каждой линии под участником.

    Обход в ширину, по одному запросу на уровень. Линий три, ширина два —
    это максимум 14 узлов, рекурсивный запрос тут был бы из пушки по
    воробьям.
    """
    counts: list[int] = []
    level = [node.pk]
    for _ in range(levels):
        children = list(
            ReferralNode.objects.filter(parent_id__in=level).values_list(
                "id", flat=True
            )
        )
        counts.append(len(children))
        if not children:
            # Ниже пусто — дальше тоже будет пусто, но длина списка должна
            # совпадать с числом линий: экран рисует все три.
            counts.extend([0] * (levels - len(counts)))
            break
        level = children
    return counts


def _sum_entries(node: ReferralNode, kind: str) -> Decimal:
    total = PointsEntry.objects.filter(node=node, kind=kind).aggregate(
        total=Sum("amount")
    )["total"]
    return total or ZERO


def summary(user) -> dict:
    """Всё, что показывает экран реферальной программы.

    Узел создаётся при первом обращении: программу включили позже, чем
    зарегистрировались первые клиенты, и без этого у них не было бы кода
    приглашения — а значит и дерево не выросло бы.
    """
    config = settings.REFERRAL
    if not config["ENABLED"]:
        # Не ошибка: программу могли выключить временно, и приложение
        # должно спокойно спрятать экран, а не показать красный текст.
        return {"enabled": False}

    node = tree.ensure_node(user)
    levels = len(config["LEVEL_PERCENTS"])
    # Заработано — и выплаты по плечам, и начисления прежней схемы: это
    # тоже баллы клиента, пропасть из «всего заработано» они не должны.
    earned = _sum_entries(node, PointsKind.PAYOUT) + _sum_entries(node, PointsKind.ACCRUAL)
    spent = _sum_entries(node, PointsKind.SPEND)
    left, right = points_service.pending_legs(node)

    return {
        "enabled": True,
        "code": node.code,
        "invite_url": invite_url(node.code),
        "balance": node.balance,
        # Потолок скидки в процентах, а не в рублях: на что его умножать,
        # станет известно только когда клиент выберет масло.
        "max_discount_percent": config["MAX_DISCOUNT_PERCENT"],
        "level_percents": [str(percent) for percent in config["LEVEL_PERCENTS"]],
        "attached": node.parent_id is not None,
        "sponsor_code": node.sponsor.code if node.sponsor_id else "",
        "invited_count": ReferralNode.objects.filter(sponsor=node).count(),
        "line_counts": line_counts(node, levels),
        "earned_total": earned,
        # Плечи до ближайшего сведения: перенос плюс пришедшее за сегодня.
        "left_leg": left,
        "right_leg": right,
        # Сколько придёт в ближайшую полночь, если до неё ничего не добавится.
        # Считает сервер: вторая копия правил в приложении однажды разошлась
        # бы с первой, и спорить с клиентом пришлось бы о цифрах.
        "expected_payout": points_service.split_payout(left, right)[0],
        "next_payout_at": points_service.next_payout_at(),
        "payout_timezone_label": config["PAYOUT_TIMEZONE_LABEL"],
        # В журнале списания лежат отрицательными — наружу отдаём модуль,
        # иначе на экране получится «потрачено −300».
        "spent_total": -spent,
    }


def entries(node: ReferralNode):
    """Журнал движений баллов, свежие сверху."""
    return (
        PointsEntry.objects.filter(node=node)
        .select_related("booking", "source_node__user")
        .order_by("-created_at")
    )


def invited(node: ReferralNode):
    """Кого этот участник привёл лично — по `sponsor`, а не по `parent`.

    Спиловер сажает приглашённого под кого-то другого, но «привёл» всё
    равно он: человеку важно видеть своих, а не тех, кто оказался под ним
    из-за переполнения.
    """
    return (
        ReferralNode.objects.filter(sponsor=node)
        .select_related("user")
        .order_by("-created_at")
    )


def invited_card(node: ReferralNode, owner: ReferralNode) -> dict:
    """Приглашённый глазами пригласившего.

    Телефон маскируем: человек согласился обслуживаться в сервисе, а не
    отдать свой номер тому, кто дал ему код. Имя показываем — без него
    список превращается в набор безымянных строк.
    """
    # Сколько баллов этот человек принёс в плечи пригласившего. Не
    # «выплачено»: выплата считается по плечам целиком, и разложить её
    # обратно по людям нельзя.
    earned = LegCredit.objects.filter(node=owner, source_node=node).aggregate(
        total=Sum("amount")
    )["total"] or ZERO

    return {
        "name": node.user.full_name or "Клиент",
        "phone_masked": mask_phone(node.user.phone),
        "joined_at": node.created_at,
        # Линия относительно пригласившего: при спиловере приглашённый
        # оказывается не на первой, и это надо видеть.
        "line": max(node.depth - owner.depth, 0),
        "earned_from": earned,
    }
