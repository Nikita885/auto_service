"""Реферальная матрица: размещение, спиловер и начисления."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.booking.constants import BookingStatus
from apps.booking.models import Booking
from apps.common.exceptions import ConflictError, NotFoundError, ValidationError
from apps.referral.constants import MatrixPosition, PointsKind
from apps.referral.models import PointsEntry
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


# ------------------------------------------------------------- начисления


def test_three_lines_get_their_percent(settings, make_user, make_booking):
    settings.REFERRAL = {
        **settings.REFERRAL,
        "LEVEL_PERCENTS": [Decimal("5"), Decimal("4"), Decimal("3")],
        "BASE": "total",
    }

    top = tree_service.ensure_node(make_user("Верх"))
    second = tree_service.attach(make_user(), top.code)
    third = tree_service.attach(make_user(), second.code)
    buyer = tree_service.attach(make_user(), third.code)

    booking = make_booking(buyer.user, work="1000", oil_price="5000")  # чек 6000
    entries = points_service.accrue_for_booking(booking)

    assert len(entries) == 3
    by_level = {entry.level: entry for entry in entries}
    assert by_level[1].node_id == third.pk
    assert by_level[1].amount == Decimal("300.00")  # 5 % от 6000
    assert by_level[2].node_id == second.pk
    assert by_level[2].amount == Decimal("240.00")  # 4 %
    assert by_level[3].node_id == top.pk
    assert by_level[3].amount == Decimal("180.00")  # 3 %

    third.refresh_from_db()
    assert third.balance == Decimal("300.00")


def test_accrual_stops_at_configured_depth(settings, make_user, make_booking):
    """Четвёртая линия вверх не получает ничего: глубину задаёт длина списка."""
    settings.REFERRAL = {
        **settings.REFERRAL,
        "LEVEL_PERCENTS": [Decimal("5"), Decimal("4"), Decimal("3")],
    }

    root = tree_service.ensure_node(make_user("Корень"))
    chain = [root]
    for _ in range(4):
        chain.append(tree_service.attach(make_user(), chain[-1].code))

    booking = make_booking(chain[-1].user)
    points_service.accrue_for_booking(booking)

    root.refresh_from_db()
    assert root.balance == Decimal("0")


def test_base_can_be_limited_to_work(settings, make_user, make_booking):
    settings.REFERRAL = {
        **settings.REFERRAL,
        "LEVEL_PERCENTS": [Decimal("5")],
        "BASE": "work",
    }

    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    buyer = tree_service.attach(make_user(), sponsor.code)

    booking = make_booking(buyer.user, work="1000", oil_price="5000")
    entries = points_service.accrue_for_booking(booking)

    assert entries[0].amount == Decimal("50.00")  # 5 % от 1000, а не от 6000


def test_accrual_is_idempotent(settings, make_user, make_booking):
    """Мастер нажал «выполнено» дважды — баллы начисляются один раз."""
    settings.REFERRAL = {**settings.REFERRAL, "LEVEL_PERCENTS": [Decimal("5")]}

    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    buyer = tree_service.attach(make_user(), sponsor.code)
    booking = make_booking(buyer.user)

    points_service.accrue_for_booking(booking)
    points_service.accrue_for_booking(booking)

    assert PointsEntry.objects.filter(kind=PointsKind.ACCRUAL).count() == 1
    sponsor.refresh_from_db()
    assert sponsor.balance == Decimal("200.00")  # 5 % от 4000 ровно один раз


def test_client_without_sponsor_generates_nothing(make_user, make_booking):
    lonely = tree_service.ensure_node(make_user("Один"))
    booking = make_booking(lonely.user)

    assert points_service.accrue_for_booking(booking) == []
    assert PointsEntry.objects.count() == 0


def test_disabled_program_accrues_nothing(settings, make_user, make_booking):
    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    buyer = tree_service.attach(make_user(), sponsor.code)
    booking = make_booking(buyer.user)

    settings.REFERRAL = {**settings.REFERRAL, "ENABLED": False}
    assert points_service.accrue_for_booking(booking) == []


def test_percent_snapshot_survives_rate_change(settings, make_user, make_booking):
    """Ставку меняют в .env — уже начисленное не переписывается."""
    settings.REFERRAL = {**settings.REFERRAL, "LEVEL_PERCENTS": [Decimal("5")]}

    sponsor = tree_service.ensure_node(make_user("Спонсор"))
    buyer = tree_service.attach(make_user(), sponsor.code)
    entry = points_service.accrue_for_booking(make_booking(buyer.user))[0]

    settings.REFERRAL = {**settings.REFERRAL, "LEVEL_PERCENTS": [Decimal("1")]}
    entry.refresh_from_db()
    assert entry.percent == Decimal("5.00")


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
