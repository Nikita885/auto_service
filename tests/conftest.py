from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.booking.services import draft as draft_service
from apps.catalog.models import Oil, OilStock, OilType, ServicePoint


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def client_user(db) -> User:
    return User.objects.create_user(
        phone="+79001112233", full_name="Иван Тестов", car_model="Kia Rio",
        car_plate="А123ВС77",
    )


@pytest.fixture
def other_user(db) -> User:
    return User.objects.create_user(phone="+79004445566", full_name="Пётр Второй")


@pytest.fixture
def master_user(db) -> User:
    return User.objects.create_master(phone="+79000000001", full_name="Мастер")


@pytest.fixture
def point(db) -> ServicePoint:
    """Точка работает круглосуточно — так тесты не зависят от времени суток."""
    return ServicePoint.objects.create(
        name="Тестовая",
        address="ул. Тестовая, 1",
        timezone="Europe/Moscow",
        opens_at=time(0, 0),
        closes_at=time(23, 30),
        workdays=[0, 1, 2, 3, 4, 5, 6],
        slot_minutes=30,
        posts_count=1,
    )


@pytest.fixture
def second_point(db) -> ServicePoint:
    return ServicePoint.objects.create(
        name="Вторая",
        address="ул. Вторая, 2",
        opens_at=time(0, 0),
        closes_at=time(23, 30),
        workdays=[0, 1, 2, 3, 4, 5, 6],
        posts_count=1,
    )


@pytest.fixture
def oil(db) -> Oil:
    return Oil.objects.create(
        brand="Shell",
        name="Helix HX8",
        viscosity="5W-30",
        oil_type=OilType.SYNTHETIC,
        volume_liters=Decimal("4.0"),
        price=Decimal("3900"),
        work_price=Decimal("900"),
    )


@pytest.fixture
def stock(db, point, oil) -> OilStock:
    return OilStock.objects.create(service_point=point, oil=oil, quantity=1)


@pytest.fixture
def auth(api):
    def _auth(user: User) -> APIClient:
        api.force_authenticate(user=user)
        return api

    return _auth


@pytest.fixture
def free_slot(point, settings):
    """Слот на завтра, заведомо далёкий от всех дедлайнов.

    Намеренно не «ближайший»: тесты подкручивают часы на минуты вперёд,
    и слот не должен из-за этого упереться в минимальный запас до визита.

    И намеренно не первый слот дня. Тестовая точка открыта с 00:00, так
    что первый слот «завтра» — это ближайшая полночь. При прогоне поздним
    вечером до неё остаётся меньше часа: минимальный запас в 30 минут она
    проходит, а дедлайн отмены в 60 минут — уже нет, и тесты отмены
    начинают падать в зависимости от времени суток.
    """
    from apps.booking.services.slots import build_slots

    now = timezone.now()
    # Дедлайн отмены плюс запас на сдвиги часов внутри самих тестов.
    margin = timedelta(minutes=settings.BOOKING["CANCEL_DEADLINE_MINUTES"] + 120)

    for offset in (1, 2):
        day = now.astimezone(point.tz).date() + timedelta(days=offset)
        for slot in build_slots(point, day):
            if slot.start_at - now >= margin:
                return slot

    raise AssertionError("Не удалось построить свободный слот для теста")


@pytest.fixture
def ready_draft(client_user, point, stock, free_slot):
    """Черновик, доведённый до шага «выбрано время»."""
    draft = draft_service.start_draft(client_user)
    draft_service.select_point(client_user, draft.pk, point.pk)
    draft_service.select_oil(client_user, draft.pk, stock.oil_id)
    return draft_service.select_slot(client_user, draft.pk, free_slot.start_at)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttling DRF живёт в кеше и протекает между тестами."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _no_real_sms(settings):
    settings.SMS = {**settings.SMS, "PROVIDER": "console"}
    from apps.notifications.providers import get_sms_provider

    get_sms_provider.cache_clear()
    yield
    get_sms_provider.cache_clear()
