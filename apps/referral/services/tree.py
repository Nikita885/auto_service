"""Матрица участников: выдача кодов и размещение новичков.

Место в матрице выбирается обходом в ширину от спонсора: заполняем уровень
целиком, слева направо, и только потом спускаемся ниже. Так дерево растёт
равномерно — это и есть «в слабое плечо», просто выраженное через порядок
обхода, а не через сравнение оборотов.
"""

from __future__ import annotations

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.common.exceptions import ConflictError, NotFoundError, ValidationError
from apps.referral.constants import MatrixPosition
from apps.referral.models import ReferralNode

# Порядок мест фиксирован: сначала левое. Обход в ширину плюс постоянный
# порядок дают предсказуемое дерево — одинаковая последовательность
# регистраций всегда даёт одинаковую матрицу.
SLOT_ORDER = (MatrixPosition.LEFT, MatrixPosition.RIGHT)

# Сколько раз пробуем занять место, если его перехватили. Конфликт возможен
# только при одновременной регистрации, и второй попытки почти всегда
# хватает; лимит нужен, чтобы не крутиться вечно на сломанных данных.
MAX_PLACEMENT_ATTEMPTS = 5


def get_node(user) -> ReferralNode | None:
    """Узел клиента, если он уже в программе."""
    return ReferralNode.objects.filter(user=user).first()


def ensure_node(user) -> ReferralNode:
    """Узел клиента, создавая его при первом обращении.

    Код приглашения выдаётся всем: клиент может никого не приводить, но
    позвать знакомого он должен иметь возможность в любой момент.
    """
    node, _ = ReferralNode.objects.get_or_create(user=user)
    return node


def find_by_code(code: str) -> ReferralNode:
    try:
        return ReferralNode.objects.get(code=code.strip().upper())
    except ReferralNode.DoesNotExist as exc:
        raise NotFoundError(
            "Такого кода приглашения нет", code="referral_code_not_found"
        ) from exc


def _iter_free_slot(sponsor: ReferralNode):
    """Первое свободное место в поддереве спонсора, обход в ширину.

    Читаем детей всего уровня одним запросом: спуск по одному узлу дал бы
    столько запросов, сколько людей в ветке.
    """
    width = len(SLOT_ORDER)
    level = [sponsor]

    while level:
        children = list(
            ReferralNode.objects.filter(parent__in=level).only(
                "id", "parent_id", "position", "depth"
            )
        )
        by_parent: dict = {}
        for child in children:
            by_parent.setdefault(child.parent_id, []).append(child)

        for node in level:
            taken = {c.position for c in by_parent.get(node.id, ())}
            if len(taken) >= width:
                continue
            for slot in SLOT_ORDER:
                if slot not in taken:
                    return node, slot

        level = children

    # Сюда не дойти: у листа оба места свободны, и цикл вернёт его раньше.
    raise ConflictError(
        "Не нашлось свободного места в матрице", code="referral_no_free_slot"
    )


@transaction.atomic
def attach(user, code: str) -> ReferralNode:
    """Поставить клиента в матрицу по коду приглашения.

    Привязка одноразовая: после неё начисления уходят конкретным людям, и
    перенос узла означал бы, что кто-то уже получил баллы за чужого
    клиента.
    """
    if not settings.REFERRAL["ENABLED"]:
        raise ConflictError(
            "Реферальная программа выключена", code="referral_disabled"
        )

    sponsor = find_by_code(code)
    node = ensure_node(user)

    if node.parent_id is not None:
        raise ConflictError(
            "Приглашение уже принято, сменить пригласившего нельзя",
            code="referral_already_attached",
        )
    if sponsor.pk == node.pk:
        raise ValidationError(
            "Нельзя пригласить самого себя", code="referral_self_invite"
        )
    if _is_descendant(sponsor, node):
        # Спонсор уже под этим клиентом: замкнули бы дерево в кольцо, и
        # обход вверх за начислениями зациклился бы.
        raise ValidationError(
            "Этот участник уже находится в вашей ветке", code="referral_cycle"
        )

    for _ in range(MAX_PLACEMENT_ATTEMPTS):
        parent, slot = _iter_free_slot(sponsor)
        node.sponsor = sponsor
        node.parent = parent
        node.position = slot
        node.depth = parent.depth + 1
        try:
            with transaction.atomic():
                node.save(update_fields=["sponsor", "parent", "position", "depth"])
            return node
        except IntegrityError:
            # Место заняли между поиском и сохранением — ищем следующее.
            continue

    raise ConflictError(
        "Не удалось занять место в матрице, попробуйте ещё раз",
        code="referral_placement_conflict",
    )


def _is_descendant(candidate: ReferralNode, ancestor: ReferralNode) -> bool:
    """Находится ли `candidate` в ветке под `ancestor`."""
    current = candidate
    # Глубина строго убывает при подъёме, так что цикл конечен даже если в
    # данных каким-то образом оказалось кольцо.
    seen = 0
    while current.parent_id is not None and seen <= current.depth + 1:
        if current.parent_id == ancestor.pk:
            return True
        current = ReferralNode.objects.only("id", "parent_id", "depth").get(
            pk=current.parent_id
        )
        seen += 1
    return False


def upline(node: ReferralNode, levels: int) -> list[ReferralNode]:
    """Вышестоящие в матрице: первый в списке — прямой родитель.

    Идём по `parent`, а не по `sponsor`: начисления получает тот, под кем
    человек реально стоит, иначе спиловер не имел бы смысла.
    """
    chain: list[ReferralNode] = []
    current = node
    while len(chain) < levels and current.parent_id is not None:
        current = ReferralNode.objects.select_related(None).get(pk=current.parent_id)
        chain.append(current)
    return chain
