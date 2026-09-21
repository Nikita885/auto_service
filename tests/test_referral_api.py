"""Внешняя часть реферальной программы: то, что видит клиентское приложение.

Ядро матрицы проверяет `test_referral.py`. Здесь — контракт API: права,
что уходит наружу, а что нет, и поведение на границах (программа
выключена, код чужой, привязка повторная).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts import services as auth_services
from apps.accounts.models import User
from apps.booking.constants import BookingStatus
from apps.booking.models import Booking
from apps.referral.constants import PointsKind
from apps.referral.models import PointsEntry, ReferralNode
from apps.referral.services import points as points_service
from apps.referral.services import tree as tree_service

pytestmark = pytest.mark.django_db

SUMMARY = "/api/v1/referral/"
ATTACH = "/api/v1/referral/attach/"
POINTS = "/api/v1/referral/points/"
INVITED = "/api/v1/referral/invited/"


@pytest.fixture
def make_user(db):
    counter = {"n": 0}

    def _make(name: str = "Клиент") -> User:
        counter["n"] += 1
        return User.objects.create_user(
            phone=f"+7911000{counter['n']:04d}", full_name=f"{name} {counter['n']}"
        )

    return _make


@pytest.fixture
def auth(api):
    def _auth(user: User):
        api.force_authenticate(user)
        return api

    return _auth


@pytest.fixture
def completed_booking(point, oil):
    def _make(user: User, *, work="1000", oil_price="3000") -> Booking:
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


# ------------------------------------------------------- узел при входе


def test_node_appears_on_registration():
    """Главная починка: раньше узел заводился только у того, кто ввёл чужой
    код. Клиент без кода обрывал цепочку начислений для всех, кто над ним,
    — и программа не работала вовсе."""
    challenge = auth_services.request_otp("+79130001122")
    result = auth_services.verify_otp("+79130001122", challenge.debug_code)

    assert result.is_new_user
    assert ReferralNode.objects.filter(user=result.user).exists()


def test_master_does_not_get_a_node(master_user):
    """Узел на сотруднике означал бы, что сервис начисляет баллы сам себе."""
    assert not ReferralNode.objects.filter(user=master_user).exists()


# ------------------------------------------------------------- сводка


def test_summary_gives_code_and_link(auth, make_user, settings):
    settings.COMPANY = {**settings.COMPANY, "SITE_URL": "https://moiservis.pro"}
    user = make_user()

    body = auth(user).get(SUMMARY).json()

    assert body["enabled"] is True
    assert body["code"]
    assert body["invite_url"] == f"https://moiservis.pro/i/{body['code']}"
    assert body["attached"] is False
    assert body["balance"] == "0.00"


def test_summary_creates_node_for_old_clients(auth, make_user):
    """Программу включили позже, чем зарегистрировались первые клиенты.
    Без ленивого создания у них не было бы кода — и дерево не выросло бы."""
    user = make_user()
    ReferralNode.objects.filter(user=user).delete()

    body = auth(user).get(SUMMARY).json()

    assert body["code"]
    assert ReferralNode.objects.filter(user=user).exists()


def test_summary_counts_lines_and_money(auth, make_user, completed_booking):
    sponsor = make_user("Спонсор")
    sponsor_node = tree_service.ensure_node(sponsor)
    first = tree_service.attach(make_user(), sponsor_node.code)
    tree_service.attach(make_user(), sponsor_node.code)
    tree_service.attach(make_user(), first.code)

    buyer = User.objects.get(pk=first.user_id)
    points_service.accrue_for_booking(completed_booking(buyer))

    body = auth(sponsor).get(SUMMARY).json()

    assert body["invited_count"] == 2
    # Две на первой линии, одна на второй, третья пустая.
    assert body["line_counts"] == [2, 1, 0]
    # 5 % от чека 4000 = 200.
    assert body["earned_total"] == "200.00"
    assert body["spent_total"] == "0.00"
    assert body["balance"] == "200.00"


def test_spent_total_is_positive_on_screen(auth, make_user, completed_booking):
    """В журнале списания лежат отрицательными. На экране «потрачено −300»
    выглядело бы как ошибка."""
    sponsor = make_user("Спонсор")
    node = tree_service.ensure_node(sponsor)
    invited = tree_service.attach(make_user(), node.code)
    points_service.accrue_for_booking(
        completed_booking(User.objects.get(pk=invited.user_id))
    )
    points_service.spend(node, Decimal("50"), comment="проверка")

    body = auth(sponsor).get(SUMMARY).json()

    assert body["spent_total"] == "50.00"
    assert body["balance"] == "150.00"


def test_summary_is_silent_when_program_is_off(auth, make_user, settings):
    settings.REFERRAL = {**settings.REFERRAL, "ENABLED": False}

    body = auth(make_user()).get(SUMMARY).json()

    assert body == {"enabled": False}


def test_client_only(auth, master_user):
    assert auth(master_user).get(SUMMARY).status_code == 403


def test_anonymous_gets_nothing(api):
    assert api.get(SUMMARY).status_code == 401


# ------------------------------------------------------------ привязка


def test_attach_by_code(auth, make_user):
    sponsor_node = tree_service.ensure_node(make_user("Спонсор"))
    user = make_user()

    body = auth(user).post(ATTACH, {"code": sponsor_node.code}, format="json").json()

    assert body["attached"] is True
    assert body["sponsor_code"] == sponsor_node.code


def test_attach_is_case_insensitive(auth, make_user):
    """Код диктуют голосом и пересылают в мессенджере — регистр по дороге
    теряется."""
    sponsor_node = tree_service.ensure_node(make_user("Спонсор"))
    user = make_user()

    response = auth(user).post(
        ATTACH, {"code": sponsor_node.code.lower()}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["attached"] is True


def test_attach_twice_is_rejected(auth, make_user):
    first = tree_service.ensure_node(make_user("Первый"))
    second = tree_service.ensure_node(make_user("Второй"))
    user = make_user()

    auth(user).post(ATTACH, {"code": first.code}, format="json")
    response = auth(user).post(ATTACH, {"code": second.code}, format="json")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "referral_already_attached"


def test_attach_to_unknown_code(auth, make_user):
    response = auth(make_user()).post(ATTACH, {"code": "ZZZZZZ"}, format="json")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "referral_code_not_found"


def test_attach_to_self_is_rejected(auth, make_user):
    user = make_user()
    node = tree_service.ensure_node(user)

    response = auth(user).post(ATTACH, {"code": node.code}, format="json")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "referral_self_invite"


# ------------------------------------------------------------- история


def test_points_history(auth, make_user, completed_booking):
    sponsor = make_user("Спонсор")
    node = tree_service.ensure_node(sponsor)
    invited = tree_service.attach(make_user(), node.code)
    booking = completed_booking(User.objects.get(pk=invited.user_id))
    points_service.accrue_for_booking(booking)

    body = auth(sponsor).get(POINTS).json()

    assert body["count"] == 1
    row = body["results"][0]
    assert row["kind"] == PointsKind.ACCRUAL
    assert row["amount"] == "200.00"
    assert row["level"] == 1
    assert row["percent"] == "5.00"
    assert row["booking_code"] == booking.code


def test_points_history_shows_only_my_entries(auth, make_user, completed_booking):
    stranger = make_user("Чужой")
    stranger_node = tree_service.ensure_node(stranger)
    invited = tree_service.attach(make_user(), stranger_node.code)
    points_service.accrue_for_booking(
        completed_booking(User.objects.get(pk=invited.user_id))
    )

    body = auth(make_user()).get(POINTS).json()

    assert body["count"] == 0
    assert PointsEntry.objects.count() == 1


# ---------------------------------------------------------- приглашённые


def test_invited_list_masks_phones(auth, make_user):
    """Человек согласился обслуживаться в сервисе, а не отдать свой номер
    тому, кто дал ему код."""
    sponsor = make_user("Спонсор")
    node = tree_service.ensure_node(sponsor)
    invited_user = make_user("Приглашённый")
    tree_service.attach(invited_user, node.code)

    rows = auth(sponsor).get(INVITED).json()

    assert len(rows) == 1
    assert rows[0]["name"] == invited_user.full_name
    assert rows[0]["phone_masked"].count("*") == 3
    assert invited_user.phone not in rows[0]["phone_masked"]


def test_invited_list_counts_money_from_each(auth, make_user, completed_booking):
    sponsor = make_user("Спонсор")
    node = tree_service.ensure_node(sponsor)
    invited = tree_service.attach(make_user(), node.code)
    points_service.accrue_for_booking(
        completed_booking(User.objects.get(pk=invited.user_id))
    )

    rows = auth(sponsor).get(INVITED).json()

    assert rows[0]["earned_from"] == "200.00"
    assert rows[0]["line"] == 1


def test_invited_list_is_by_sponsor_not_by_parent(auth, make_user):
    """Спиловер сажает приглашённого под кого-то другого, но «привёл» всё
    равно тот, чей код ввели."""
    sponsor = make_user("Спонсор")
    node = tree_service.ensure_node(sponsor)
    for _ in range(3):
        tree_service.attach(make_user(), node.code)

    rows = auth(sponsor).get(INVITED).json()

    # Под спонсором только два места, третий упал ниже — но привёл его он.
    assert len(rows) == 3
    assert {row["line"] for row in rows} == {1, 2}


# ------------------------------------------------ публичная проверка кода


def test_code_check_is_open_and_tells_only_the_name(api, make_user):
    inviter = make_user("Пригласивший")
    node = tree_service.ensure_node(inviter)

    body = api.get(f"/api/v1/referral/codes/{node.code}/").json()

    assert body == {"code": node.code, "inviter_name": inviter.full_name}


def test_code_check_on_unknown_code(api):
    response = api.get("/api/v1/referral/codes/ZZZZZZ/")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "referral_code_not_found"
