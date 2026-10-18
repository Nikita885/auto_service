"""Услуги по категориям: модели, ограничения и перенос масел.

Главное здесь — перенос на заполненной базе и обратно: масла уже лежат в
живых записях, и миграция обязана не потерять ни рубля, ни истории.
Остальное — ограничения, которые ловят ошибку до того, как она доедет до
денег: материал не больше цены, названия не дублируются, — и мост из
старого раздела масел в услуги: пока панель мастера правит масла, цифры
обязаны доезжать до услуг, иначе клиент увидит прежнюю цену.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.accounts.models import User
from apps.catalog.models import Service, ServiceCategory, ServiceJournalKind
from apps.catalog.services import oils as oils_service
from apps.garage.models import EntryKind

pytestmark = pytest.mark.django_db(transaction=True)


# ----------------------------------------------------------- вид для дневника
def test_journal_kinds_are_a_subset_of_garage_kinds():
    """Вид категории попадает в дневник водителя как есть.

    `catalog` не может импортировать `garage` (тот сам зависит от
    справочника марок), поэтому перечисление повторено. Этот тест —
    единственное, что держит обе копии вместе.
    """
    assert set(ServiceJournalKind.values) <= set(EntryKind.values)
    assert ServiceJournalKind.OIL == EntryKind.OIL


# ---------------------------------------------------------------- ограничения
def test_material_above_price_is_rejected(point):
    category = ServiceCategory.objects.create(service_point=point, name="Мойка")
    with pytest.raises(IntegrityError), transaction.atomic():
        Service.objects.create(
            category=category, name="Мойка кузова",
            price=Decimal("500"), material_price=Decimal("600"),
        )


def test_service_name_is_unique_inside_category(point):
    category = ServiceCategory.objects.create(service_point=point, name="Мойка")
    Service.objects.create(category=category, name="Мойка кузова", price=Decimal("500"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Service.objects.create(category=category, name="Мойка кузова", price=Decimal("700"))


def test_category_name_is_unique_per_point_but_free_on_another(point, second_point):
    """Каталог у каждой точки свой: одно и то же название на двух адресах —
    это две разные категории со своими ценами."""
    ServiceCategory.objects.create(service_point=point, name="Замена резины")
    ServiceCategory.objects.create(service_point=second_point, name="Замена резины")

    with pytest.raises(IntegrityError), transaction.atomic():
        ServiceCategory.objects.create(service_point=point, name="Замена резины")


def test_work_price_is_price_without_material(point):
    category = ServiceCategory.objects.create(service_point=point, name="Замена масла")
    service = Service.objects.create(
        category=category, name="Shell 5W-30",
        price=Decimal("4800"), material_price=Decimal("3900"),
    )
    assert service.work_price == Decimal("900")
    assert service.total_price == Decimal("4800")
    assert service.service_point_id == point.pk


# --------------------------------------------- мост из масел в услуги
def test_new_oil_becomes_a_service_on_every_point(master_user, point, second_point):
    """Новое масло раньше появлялось в общем каталоге сети — значит, услуга
    должна появиться на каждой точке, даже там, где остаток не задали."""
    oils_service.create_oil(
        master_user,
        stock={point.pk: 3},
        brand="Shell", name="Helix HX8", viscosity="5W-30", oil_type="synthetic",
        volume_liters=Decimal("4.0"), price=Decimal("3900"), work_price=Decimal("900"),
    )

    rows = {
        row.category.service_point_id: row
        for row in Service.objects.select_related("category")
    }
    assert set(rows) == {point.pk, second_point.pk}
    assert (rows[point.pk].quantity, rows[second_point.pk].quantity) == (3, 0)
    assert rows[point.pk].name == "Shell Helix HX8 5W-30, 4.0 л"
    assert (rows[point.pk].price, rows[point.pk].material_price) == (
        Decimal("4800.00"), Decimal("3900.00"),
    )
    assert rows[point.pk].is_limited is True
    assert rows[point.pk].category.journal_kind == ServiceJournalKind.OIL


def test_oil_price_and_flag_reach_the_service(master_user, point, oil):
    oils_service.set_stock(master_user, oil.pk, point.pk, 5)

    oils_service.update_oil(
        master_user, oil.pk,
        price=Decimal("4100"), work_price=Decimal("1000"), is_active=False,
    )

    service = Service.objects.get(category__service_point=point, oil=oil)
    assert (service.price, service.material_price) == (Decimal("5100.00"), Decimal("4100.00"))
    assert service.is_active is False
    # Пересчёт цены не трогает полку.
    assert service.quantity == 5


def test_stock_change_touches_only_its_own_point(master_user, point, second_point, oil):
    oils_service.set_stock(master_user, oil.pk, point.pk, 4)
    oils_service.set_stock(master_user, oil.pk, second_point.pk, 1)

    oils_service.set_stock(master_user, oil.pk, point.pk, 9)

    rows = {
        row.category.service_point_id: row.quantity
        for row in Service.objects.select_related("category")
    }
    assert rows == {point.pk: 9, second_point.pk: 1}


# ------------------------------------------------------------ перенос масел
#: Схема до услуг: масла общие на сеть, у записи одна ссылка на канистру.
BEFORE = [
    ("catalog", "0003_service_point_timezone_workdays"),
    ("booking", "0005_oil_on_site"),
]
#: Схема с услугами, но до переноса данных — на ней проверяется обратный ход.
EMPTY = [
    ("catalog", "0004_services"),
    ("booking", "0006_booking_services"),
]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state([t for t in targets if t[1]]).apps


def _leaves():
    return MigrationExecutor(connection).loader.graph.leaf_nodes()


def test_oils_migrate_to_services_and_back():
    """Заполненная база: масла становятся услугами на каждой точке со своим
    остатком, записи получают позиции, а откат возвращает прежний мир."""
    try:
        _check_roundtrip()
    finally:
        _migrate(_leaves())  # следующим тестам нужна полная схема даже после падения


def _check_roundtrip():
    old = _migrate(BEFORE)
    Point = old.get_model("catalog", "ServicePoint")
    Oil = old.get_model("catalog", "Oil")
    OilStock = old.get_model("catalog", "OilStock")
    OldBooking = old.get_model("booking", "Booking")
    OldDraft = old.get_model("booking", "BookingDraft")

    north = Point.objects.create(name="Северная", address="ул. Северная, 1")
    south = Point.objects.create(name="Южная", address="ул. Южная, 2")
    shell = Oil.objects.create(
        brand="Shell", name="Helix HX8", viscosity="5W-30", oil_type="synthetic",
        volume_liters=Decimal("4.0"), price=Decimal("3900"), work_price=Decimal("900"),
    )
    total = Oil.objects.create(
        brand="Total", name="Quartz 7000", viscosity="10W-40", oil_type="semi_synthetic",
        volume_liters=Decimal("5.0"), price=Decimal("2400"), work_price=Decimal("800"),
        is_active=False,
    )
    # Остаток есть только у Shell и только на двух точках по-разному;
    # у Total строки остатка нет вовсе — услуга должна появиться с нулём.
    OilStock.objects.create(service_point=north, oil=shell, quantity=7)
    OilStock.objects.create(service_point=south, oil=shell, quantity=2)

    client = User.objects.create_user(phone="+79001110001", full_name="Клиент")
    start = datetime(2026, 1, 10, 9, tzinfo=UTC)

    with_oil = OldBooking.objects.create(
        code="OIL001", user_id=client.pk, service_point=north, oil=shell,
        start_at=start, end_at=start + timedelta(minutes=30), status="completed",
        client_phone=client.phone, oil_title="Shell Helix HX8 5W-30, 4.0 л",
        oil_price=Decimal("3900"), work_price=Decimal("900"), total_price=Decimal("4800"),
        final_price=Decimal("5000"), points_spent=Decimal("100"),
    )
    on_site = OldBooking.objects.create(
        code="SITE01", user_id=client.pk, service_point=south, oil=None,
        start_at=start + timedelta(days=1), end_at=start + timedelta(days=1, minutes=30),
        client_phone=client.phone, oil_title="Подберём на месте",
        oil_price=Decimal("0"), work_price=Decimal("0"), total_price=Decimal("0"),
    )

    def draft(phone, **kwargs):
        user = User.objects.create_user(phone=phone)
        return OldDraft.objects.create(
            user_id=user.pk, expires_at=start + timedelta(days=30), **kwargs
        )

    picked = draft("+79001110002", service_point=north, oil=shell, step="oil_selected")
    asked = draft("+79001110003", service_point=south, oil_on_site=True, step="oil_selected")
    early = draft("+79001110004", service_point=north, step="point_selected")

    # ---------------------------------------------------------------- вперёд
    new = _migrate(_leaves())
    Category = new.get_model("catalog", "ServiceCategory")
    NewService = new.get_model("catalog", "Service")
    NewBooking = new.get_model("booking", "Booking")
    Item = new.get_model("booking", "BookingItem")
    NewDraft = new.get_model("booking", "BookingDraft")

    # Категория «Замена масла» — на каждой точке своя, первой в списке и с
    # видом «масло»: только он двигает напоминание о замене у клиента.
    assert Category.objects.count() == 2
    north_category = Category.objects.get(service_point_id=north.pk)
    assert (north_category.name, north_category.journal_kind) == ("Замена масла", "oil")
    assert (north_category.sort_order, north_category.allow_on_site) == (10, True)

    # Два масла на двух точках — четыре услуги со своими остатками.
    assert NewService.objects.count() == 4
    north_shell = NewService.objects.get(category=north_category, oil=shell.pk)
    south_shell = NewService.objects.get(category__service_point_id=south.pk, oil=shell.pk)
    assert north_shell.name == "Shell Helix HX8 5W-30, 4.0 л"
    assert (north_shell.price, north_shell.material_price) == (
        Decimal("4800.00"), Decimal("3900.00"),
    )
    assert (north_shell.quantity, south_shell.quantity) == (7, 2)
    assert north_shell.is_limited is True and north_shell.is_active is True
    # Масло без строки остатка — услуга с нулём, а не потерянная позиция.
    assert NewService.objects.get(category=north_category, oil=total.pk).quantity == 0
    # Снятое с продажи масло остаётся выключенной услугой.
    assert NewService.objects.get(category=north_category, oil=total.pk).is_active is False

    # Запись с маслом: одна позиция с суммой брони и снимками.
    moved = NewBooking.objects.get(pk=with_oil.pk)
    assert (moved.category_title, moved.service_title) == ("Замена масла", with_oil.oil_title)
    assert (moved.material_price, moved.service_on_site) == (Decimal("3900.00"), False)
    assert moved.service_category_id == north_category.pk
    item = Item.objects.get(booking=moved)
    assert (item.service_id, item.quantity) == (north_shell.pk, 1)
    assert (item.price, item.material_price) == (Decimal("4800.00"), Decimal("3900.00"))
    # Деньги не пересчитаны: итог мастера и списанные баллы на месте.
    assert (moved.total_price, moved.final_price, moved.points_spent) == (
        Decimal("4800.00"), Decimal("5000.00"), Decimal("100.00"),
    )

    # «Подберут на месте»: позиций нет, но категория и флаг есть — по ним
    # запись попадает в очередь звонков.
    waiting = NewBooking.objects.get(pk=on_site.pk)
    assert (waiting.service_on_site, Item.objects.filter(booking=waiting).count()) == (True, 0)
    assert waiting.service_category_id == Category.objects.get(service_point_id=south.pk).pk

    # Черновики: выбранное масло → услуга своей точки; «на месте» → флаг;
    # не дошедший до шага услуги остаётся без категории, иначе воронка
    # записи показала бы шаг, которого не было.
    assert NewDraft.objects.get(pk=picked.pk).service_id == north_shell.pk
    assert NewDraft.objects.get(pk=picked.pk).on_site is False
    assert NewDraft.objects.get(pk=asked.pk).service_id is None
    assert NewDraft.objects.get(pk=asked.pk).on_site is True
    assert NewDraft.objects.get(pk=early.pk).service_category_id is None

    # Услуга, которую мастер завёл сам, и запись, созданная уже новым кодом.
    own = NewService.objects.create(
        category=north_category, name="Долив антифриза", price=Decimal("300"),
        material_price=Decimal("200"), sort_order=100,
    )
    fresh = NewBooking.objects.create(
        code="NEW001", user_id=client.pk, service_point_id=north.pk,
        service_category=north_category, category_title="Замена масла",
        service_title=north_shell.name, start_at=start + timedelta(days=2),
        end_at=start + timedelta(days=2, minutes=30), client_phone=client.phone,
        oil_title="", oil_price=Decimal("0"), work_price=Decimal("900"),
        material_price=Decimal("3900"), total_price=Decimal("4800"),
    )
    Item.objects.create(
        booking=fresh, service=north_shell, title=north_shell.name,
        category_title="Замена масла", price=Decimal("4800"),
        material_price=Decimal("3900"), quantity=1,
    )
    washed = NewBooking.objects.create(
        code="NEW002", user_id=client.pk, service_point_id=north.pk,
        service_category=north_category, category_title="Замена масла",
        service_title=own.name, start_at=start + timedelta(days=3),
        end_at=start + timedelta(days=3, minutes=30), client_phone=client.phone,
        oil_title="", oil_price=Decimal("0"), work_price=Decimal("100"),
        material_price=Decimal("200"), total_price=Decimal("300"),
    )
    Item.objects.create(
        booking=washed, service=own, title=own.name, category_title="Замена масла",
        price=Decimal("300"), material_price=Decimal("200"), quantity=1,
    )

    # ------------------------------------------------- назад: только данные
    mid = _migrate(EMPTY)
    MidService = mid.get_model("catalog", "Service")
    MidCategory = mid.get_model("catalog", "ServiceCategory")
    MidItem = mid.get_model("booking", "BookingItem")
    MidBooking = mid.get_model("booking", "Booking")

    assert MidItem.objects.count() == 0
    # Услуги, выросшие из масел, удалены; своя услуга мастера — нет.
    assert list(MidService.objects.values_list("name", flat=True)) == ["Долив антифриза"]
    # Категория точки, где осталась работа мастера, живёт; опустевшая — нет.
    assert [c.service_point_id for c in MidCategory.objects.all()] == [north.pk]

    # Записи, созданные новым кодом, читаются старым: услуге с маслом
    # возвращены поля канистры.
    restored = MidBooking.objects.get(pk=fresh.pk)
    assert restored.oil_id == shell.pk
    assert (restored.oil_title, restored.oil_price, restored.work_price) == (
        north_shell.name, Decimal("3900.00"), Decimal("900.00"),
    )
    # Услуга без масла в старую схему не ложится: название видно, ссылки нет.
    not_oil = MidBooking.objects.get(pk=washed.pk)
    assert (not_oil.oil_id, not_oil.oil_title) == (None, "Долив антифриза")
    # Перенесённые записи свои поля масла не теряли вовсе.
    assert MidBooking.objects.get(pk=with_oil.pk).oil_id == shell.pk

    # --------------------------------------------- назад: прежняя схема целиком
    back = _migrate(BEFORE)
    BackOil = back.get_model("catalog", "Oil")
    BackStock = back.get_model("catalog", "OilStock")
    BackBooking = back.get_model("booking", "Booking")

    assert BackOil.objects.count() == 2
    assert sorted(BackStock.objects.values_list("quantity", flat=True)) == [2, 7]
    kept = BackBooking.objects.get(pk=with_oil.pk)
    assert (kept.oil_title, kept.total_price) == (with_oil.oil_title, Decimal("4800.00"))
    assert "catalog_service" not in connection.introspection.table_names()
