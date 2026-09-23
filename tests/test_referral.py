"""Реферальная матрица: размещение, спиловер и начисления."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.booking.constants import BookingStatus
from apps.booking.models import Booking
from apps.common.exceptions import ConflictError, NotFoundError, ValidationError
from apps.referral.constants import MatrixPosition, PointsKind
from apps.referral.models import BinarySettlement, LegCredit, PointsEntry
from apps.referral.services import points as points_service
from apps.referral.services import tree as tree_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def make_user(db):
    """Клиенты с разными телефонами: телефон — логин, он уникален."""
    counter = {"n": 0}

    def _make(name: str = "Клиент") -> User:
        counter["n"] += 1
        return User.objects.create_user(
            phone=f"+7900000{counter['n']:04d}", full_name=f"{name} {counter['n']}"
        )

    return _make


@pytest.fixture
def make_booking(point, oil):
    """Выполненная запись с заданным чеком, мимо сервисного слоя.

    Начисления проверяем отдельно от сценария работы мастера: тот тянет за
    собой склад, слоты и переходы статусов, к матрице отношения не имеющие.
    """

    def _make(user: User, *, work: str = "1000", oil_price: str = "3000") -> Booking:
        start = timezone.now() + timedelta(days=1)
        return Booking.objects.create(
            user=user,
            service_point=point,
            oil=oil,
            start_at=start,
            end_at=start + timedelta(minutes=40),
            status=BookingStatus.COMPLETED,
            client_phone=user.phone,
            oil_title=str(oil),
            oil_price=Decimal(oil_price),
            work_price=Decimal(work),
            total_price=Decimal(oil_price) + Decimal(work),
        )

    return _make


# ------------------------------------------------------------- размещение


def test_first_invited_takes_left_slot(make_user):
    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    invited = tree_service.attach(make_user(), sponsor.code)

    assert invited.parent_id == sponsor.pk
    assert invited.position == MatrixPosition.LEFT
    assert invited.depth == 1
    assert invited.sponsor_id == sponsor.pk


def test_matrix_fills_level_before_going_deeper(make_user):
    """Третий приглашённый не помещается на первую линию и падает ниже.

    Это и есть спиловер: он капает тому, кто стоит под спонсором, даже если
    сам никого не приводил.
    """
    sponsor = tree_service.ensure_node(make_user("Спонсор"))

    first = tree_service.attach(make_user(), sponsor.code)
    second = tree_service.attach(make_user(), sponsor.code)
    third = tree_service.attach(make_user(), sponsor.code)

    assert {first.position, second.position} == {
        MatrixPosition.LEFT,
        MatrixPosition.RIGHT,
    }
    assert first.depth == second.depth == 1
    # Третий ушёл на второй уровень, но пригласившим остался спонсор.
    assert third.depth == 2
    assert third.parent_id == first.pk
    assert third.sponsor_id == sponsor.pk


def test_level_is_filled_left_to_right(make_user):
    """Обход в ширину: уровень заполняется целиком, дерево растёт ровно."""
    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    nodes = [tree_service.attach(make_user(), sponsor.code) for _ in range(6)]

    depths = [node.depth for node in nodes]
    assert depths == [1, 1, 2, 2, 2, 2]


def test_attach_is_one_time(make_user):
    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    other = tree_service.ensure_node(make_user("Другой"))
    user = make_user()

    tree_service.attach(user, sponsor.code)
    with pytest.raises(ConflictError) as exc:
        tree_service.attach(user, other.code)
    assert exc.value.code == "referral_already_attached"


def test_cannot_invite_self(make_user):
    node = tree_service.ensure_node(make_user())
    with pytest.raises(ValidationError) as exc:
        tree_service.attach(node.user, node.code)
    assert exc.value.code == "referral_self_invite"


def test_cannot_close_the_tree_into_a_loop(make_user):
    """Спонсор из своей же ветки замкнул бы обход вверх в кольцо."""
    top = tree_service.ensure_node(make_user("Верх"))
    middle = tree_service.attach(make_user(), top.code)

    with pytest.raises(ValidationError) as exc:
        tree_service.attach(top.user, middle.code)
    assert exc.value.code == "referral_cycle"


def test_unknown_code_is_rejected(make_user):
    with pytest.raises(NotFoundError):
        tree_service.attach(make_user(), "ZZZZZZ")


# ------------------------------------------------ баллы в плечи и выплаты
FIVE_FOUR_THREE = [Decimal("5"), Decimal("4"), Decimal("3")]


@pytest.fixture
def binary(settings):
    settings.REFERRAL = {
        **settings.REFERRAL,
        "ENABLED": True,
        "LEVEL_PERCENTS": FIVE_FOUR_THREE,
        "BASE": "total",
        "PAYOUT_TIMEZONE": "Asia/Yekaterinburg",
    }


def settle_tomorrow() -> None:
    """Свести всё, что пришло сегодня, — как ночная задача после 00:00."""
    points_service.settle_due_days(now=timezone.now() + timedelta(days=1))


def pay(user, make_booking, total: int):
    """Выполненная запись на `total` рублей и баллы с неё в плечи."""
    booking = make_booking(user, work="0", oil_price=str(total))
    return points_service.credit_legs_for_booking(booking)


def test_credits_go_to_the_leg_where_the_buyer_stands(binary, make_user, make_booking):
    top = tree_service.ensure_node(make_user("Верх"))
    left = tree_service.attach(make_user(), top.code)
    right = tree_service.attach(make_user(), top.code)
    assert (left.position, right.position) == (MatrixPosition.LEFT, MatrixPosition.RIGHT)

    [credit] = pay(right.user, make_booking, 6000)

    assert credit.node_id == top.pk
    assert credit.side == MatrixPosition.RIGHT
    assert credit.amount == Decimal("300.00")  # 5 % от 6000
    top.refresh_from_db()
    assert top.balance == 0  # до ночного сведения на баланс ничего не падает


def test_full_tree_pays_exactly_like_the_spreadsheet(binary, make_user, make_booking):
    """Таблица заказчика: чек 6000, линии 5/4/3 % — 600 + 960 + 1440 = 3000.

    Полное дерево на три линии вниз (2 + 4 + 8 человек), каждый оплатил
    замену. Плечи сходятся ровно (1500 слева и справа), и по правилу
    «равны — выплачиваются оба» участник получает 3000 баллов.
    """
    top = tree_service.ensure_node(make_user("Верх"))
    people = [tree_service.attach(make_user(), top.code) for _ in range(14)]
    assert sorted({p.depth - top.depth for p in people}) == [1, 2, 3]

    for person in people:
        pay(person.user, make_booking, 6000)
    settle_tomorrow()

    top.refresh_from_db()
    assert top.balance == Decimal("3000.00")
    assert (top.carry_left, top.carry_right) == (0, 0)
    entry = PointsEntry.objects.get(node=top, kind=PointsKind.PAYOUT)
    assert entry.amount == Decimal("3000.00")


def test_no_payout_while_one_leg_is_empty(binary, make_user, make_booking):
    top = tree_service.ensure_node(make_user("Верх"))
    left = tree_service.attach(make_user(), top.code)

    pay(left.user, make_booking, 6000)
    settle_tomorrow()

    top.refresh_from_db()
    assert top.balance == 0
    assert (top.carry_left, top.carry_right) == (Decimal("300.00"), 0)
    assert not PointsEntry.objects.filter(node=top).exists()


def test_weak_leg_is_paid_and_the_excess_carries_over(binary, make_user, make_booking):
    """Слева 300, справа 500 — выплата 300, справа переносится 200."""
    top = tree_service.ensure_node(make_user("Верх"))
    left = tree_service.attach(make_user(), top.code)
    right = tree_service.attach(make_user(), top.code)

    pay(left.user, make_booking, 6000)    # 300 слева
    pay(right.user, make_booking, 10000)  # 500 справа
    settle_tomorrow()

    top.refresh_from_db()
    assert top.balance == Decimal("300.00")
    assert (top.carry_left, top.carry_right) == (0, Decimal("200.00"))


def test_equal_legs_are_both_paid(binary, make_user, make_booking):
    top = tree_service.ensure_node(make_user("Верх"))
    left = tree_service.attach(make_user(), top.code)
    right = tree_service.attach(make_user(), top.code)

    pay(left.user, make_booking, 6000)
    pay(right.user, make_booking, 6000)
    settle_tomorrow()

    top.refresh_from_db()
    assert top.balance == Decimal("600.00")
    assert (top.carry_left, top.carry_right) == (0, 0)


def test_carry_waits_for_the_other_leg(binary, make_user, make_booking):
    """Одно плечо пустое — всё ждёт; пришло второе — выплата с учётом переноса."""
    top = tree_service.ensure_node(make_user("Верх"))
    left = tree_service.attach(make_user(), top.code)
    right = tree_service.attach(make_user(), top.code)

    pay(left.user, make_booking, 6000)
    settle_tomorrow()
    top.refresh_from_db()
    assert top.balance == 0

    # Второе плечо приходит на следующие сутки: вчерашние уже сведены.
    [credit] = pay(right.user, make_booking, 6000)
    LegCredit.objects.filter(pk=credit.pk).update(created_at=timezone.now() + timedelta(days=1))
    points_service.settle_due_days(now=timezone.now() + timedelta(days=2))
    top.refresh_from_db()
    assert top.balance == Decimal("600.00")  # 300 перенесённых + 300 новых, равны


def test_missed_nights_are_settled_one_by_one(binary, make_user, make_booking):
    """Воркер пролежал две ночи — сутки сводятся по отдельности и по порядку.

    День 1: слева 300, справа 500 → выплата 300, справа переносится 200.
    День 2: слева 200 → 200 и 200 равны → выплата 400. Итого 700. Если бы
    дни слили в один (слева 500, справа 500), вышло бы 1000 — неверно.
    """
    top = tree_service.ensure_node(make_user("Верх"))
    left = tree_service.attach(make_user(), top.code)
    right = tree_service.attach(make_user(), top.code)
    now = timezone.now()

    day1 = pay(left.user, make_booking, 6000) + pay(right.user, make_booking, 10000)
    day2 = pay(left.user, make_booking, 4000)
    LegCredit.objects.filter(pk__in=[c.pk for c in day1]).update(
        created_at=now - timedelta(days=2)
    )
    LegCredit.objects.filter(pk__in=[c.pk for c in day2]).update(
        created_at=now - timedelta(days=1)
    )

    points_service.settle_due_days(now=now)

    top.refresh_from_db()
    assert top.balance == Decimal("700.00")
    assert BinarySettlement.objects.filter(node=top).count() == 2


def test_settlement_happens_at_chelyabinsk_midnight(binary, make_user, make_booking):
    """Сутки кончаются в 00:00 по Челябинску (UTC+5), а не по Москве и не по UTC."""
    top = tree_service.ensure_node(make_user("Верх"))
    left = tree_service.attach(make_user(), top.code)
    right = tree_service.attach(make_user(), top.code)

    # 23:30 по Челябинску = 18:30 UTC.
    evening = datetime(2026, 9, 23, 18, 30, tzinfo=UTC)
    credits = pay(left.user, make_booking, 6000) + pay(right.user, make_booking, 6000)
    LegCredit.objects.filter(pk__in=[c.pk for c in credits]).update(created_at=evening)

    # 23:50 по Челябинску — сутки ещё идут.
    points_service.settle_due_days(now=datetime(2026, 9, 23, 18, 50, tzinfo=UTC))
    top.refresh_from_db()
    assert top.balance == 0

    # 00:05 по Челябинску — сутки 23.09 закончились.
    points_service.settle_due_days(now=datetime(2026, 9, 23, 19, 5, tzinfo=UTC))
    top.refresh_from_db()
    assert top.balance == Decimal("600.00")
    assert BinarySettlement.objects.get(node=top).day.isoformat() == "2026-09-23"


def test_settlement_and_credits_are_idempotent(binary, make_user, make_booking):
    """Повторное «Выполнено» и повторный запуск ночной задачи не удваивают баллы."""
    top = tree_service.ensure_node(make_user("Верх"))
    left = tree_service.attach(make_user(), top.code)
    right = tree_service.attach(make_user(), top.code)

    booking = make_booking(left.user, work="0", oil_price="6000")
    points_service.credit_legs_for_booking(booking)
    points_service.credit_legs_for_booking(booking)
    pay(right.user, make_booking, 6000)
    assert LegCredit.objects.count() == 2

    settle_tomorrow()
    settle_tomorrow()

    top.refresh_from_db()
    assert top.balance == Decimal("600.00")


def test_only_three_lines_get_credits(binary, make_user, make_booking):
    """Четвёртая линия вверх не получает ничего: глубину задаёт длина списка."""
    root = tree_service.ensure_node(make_user("Корень"))
    chain = [root]
    for _ in range(4):
        chain.append(tree_service.attach(make_user(), chain[-1].code))

    credits = pay(chain[-1].user, make_booking, 6000)

    assert [(c.level, c.amount) for c in credits] == [
        (1, Decimal("300.00")), (2, Decimal("240.00")), (3, Decimal("180.00")),
    ]
    assert not LegCredit.objects.filter(node=root).exists()


def test_points_paid_part_generates_no_points(binary, make_user, make_booking):
    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    buyer = tree_service.attach(make_user(), sponsor.code)
    booking = make_booking(buyer.user, work="1000", oil_price="5000")  # 6000
    booking.points_spent = Decimal("2000")
    booking.save(update_fields=["points_spent"])

    [credit] = points_service.credit_legs_for_booking(booking)

    assert credit.base_amount == Decimal("4000")
    assert credit.amount == Decimal("200.00")  # 5 % от 4000 заплаченных деньгами


def test_base_can_be_limited_to_work(binary, settings, make_user, make_booking):
    settings.REFERRAL = {**settings.REFERRAL, "BASE": "work"}
    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    buyer = tree_service.attach(make_user(), sponsor.code)

    [credit] = points_service.credit_legs_for_booking(
        make_booking(buyer.user, work="1000", oil_price="5000")
    )
    assert credit.amount == Decimal("50.00")


def test_client_without_sponsor_generates_nothing(binary, make_user, make_booking):
    lonely = tree_service.ensure_node(make_user("Один"))
    assert pay(lonely.user, make_booking, 6000) == []


def test_disabled_program_generates_nothing(binary, settings, make_user, make_booking):
    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    buyer = tree_service.attach(make_user(), sponsor.code)
    settings.REFERRAL = {**settings.REFERRAL, "ENABLED": False}
    assert pay(buyer.user, make_booking, 6000) == []


def test_percent_snapshot_survives_rate_change(binary, settings, make_user, make_booking):
    """Ставку меняют в .env — уже пришедшее в плечо не переписывается."""
    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    buyer = tree_service.attach(make_user(), sponsor.code)
    [credit] = pay(buyer.user, make_booking, 6000)

    settings.REFERRAL = {**settings.REFERRAL, "LEVEL_PERCENTS": [Decimal("1")]}
    credit.refresh_from_db()
    assert credit.percent == Decimal("5.00")


@pytest.mark.parametrize(
    ("left", "right", "paid", "left_after", "right_after"),
    [
        ("0", "500", "0", "0", "500"),
        ("300", "300", "600", "0", "0"),
        ("300", "500", "300", "0", "200"),
        ("700", "200", "200", "500", "0"),
    ],
)
def test_split_payout_rule(left, right, paid, left_after, right_after):
    assert points_service.split_payout(Decimal(left), Decimal(right)) == (
        Decimal(paid), Decimal(left_after), Decimal(right_after),
    )


def test_spend_cap_applies_to_the_whole_receipt(settings, make_user, make_booking):
    """Потолок оплаты баллами — на чек, а не на одно списание.

    Два списания по половине чека проходили оба, и запись закрывалась
    баллами целиком, хотя потолок в настройках — 50 %.
    """
    settings.REFERRAL = {**settings.REFERRAL, "MAX_DISCOUNT_PERCENT": 50}
    user = make_user()
    node = tree_service.ensure_node(user)
    node.balance = Decimal("10000")
    node.save(update_fields=["balance"])
    booking = make_booking(user, work="1000", oil_price="3000")  # чек 4000, потолок 2000

    points_service.spend(node, Decimal("1500"), booking=booking)

    with pytest.raises(ConflictError) as exc:
        points_service.spend(node, Decimal("1000"), booking=booking)
    assert exc.value.code == "points_limit_exceeded"
    assert exc.value.details["limit"] == "500.00"

    points_service.spend(node, Decimal("500"), booking=booking)
    node.refresh_from_db()
    assert node.balance == Decimal("8000")
