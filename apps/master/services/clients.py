"""Клиент глазами мастера: поиск по номеру и карточка.

Мастер ищет клиента во время звонка, а номер ему диктуют как угодно:
«8 900 123-45-67», «+7 900…», «последние цифры 4567». Полный номер
приводится к E.164 и ищется точно; от четырёх до девяти цифр —
окончание номера: на точке таких совпадений единицы, а клиент как раз
так и называет номер, «на 4567».

Карточка — одним ответом: имя, машины, записи, баллы, кто пригласил,
звонки. Записи и звонки — только по точкам сотрудника: о том, что было
на чужом адресе, мастеру знать незачем. Машины и баллы — клиентские,
они от точки не зависят.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from apps.accounts.constants import UserRole
from apps.accounts.models import User
from apps.booking.constants import ACTIVE_BOOKING_STATUSES
from apps.booking.models import Booking
from apps.booking.services import calls as calls_service
from apps.common.exceptions import NotFoundError, ValidationError
from apps.common.phone import mask_phone, normalize_phone
from apps.garage.services import cars as cars_service
from apps.referral.services import points as referral_points
from apps.referral.services import tree as referral_tree

#: Меньше четырёх цифр — это не номер, а половина базы клиентов.
MIN_DIGITS = 4
#: Сколько найденных клиентов отдать: дальше человек уточнит номер.
SEARCH_LIMIT = 20
#: Сколько прошлых записей показать в карточке — история, не архив.
PAST_LIMIT = 10
#: Сколько последних звонков показать в карточке.
CALLS_LIMIT = 10


def search(raw: str) -> list[User]:
    """Клиенты по номеру в любой записи или по его окончанию."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) < MIN_DIGITS:
        raise ValidationError(
            f"Введите номер или хотя бы {MIN_DIGITS} последние цифры",
            code="phone_too_short",
        )
    # Машины — одним запросом на всех: строка списка показывает основную.
    clients = User.objects.filter(role=UserRole.CLIENT, is_active=True).prefetch_related("cars")
    if len(digits) >= 10:
        try:
            phone = normalize_phone(raw)
        except ValidationError:
            # «8900…» без пробелов phonenumbers разбирает не всегда — тогда
            # ищем по последним десяти цифрам, это тот же номер.
            return list(clients.filter(phone__endswith=digits[-10:])[:SEARCH_LIMIT])
        return list(clients.filter(phone=phone)[:SEARCH_LIMIT])
    return list(clients.filter(phone__endswith=digits).order_by("full_name")[:SEARCH_LIMIT])


def _client(client_id) -> User:
    try:
        return User.objects.get(pk=client_id, role=UserRole.CLIENT)
    except (User.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Клиент не найден", code="client_not_found") from exc


@dataclass
class ClientCard:
    client: User
    cars: list = field(default_factory=list)
    upcoming: list = field(default_factory=list)
    past: list = field(default_factory=list)
    balance: object = None
    max_discount_percent: int = 0
    next_quote: dict | None = None
    invited_by: dict | None = None
    calls: list = field(default_factory=list)


def card(staff, client_id) -> ClientCard:
    """Всё о клиенте, что нужно мастеру с трубкой у уха, — одним вызовом."""
    client = _client(client_id)
    bookings = (
        Booking.objects.filter(user=client)
        .select_related("service_point", "service_category", "user__referral_node")
        .prefetch_related("items")
    )
    allowed = staff.accessible_point_ids()
    if allowed is not None:
        bookings = bookings.filter(service_point_id__in=allowed)

    now = timezone.now()
    upcoming = list(
        bookings.filter(status__in=ACTIVE_BOOKING_STATUSES, start_at__gte=now).order_by("start_at")
    )
    past = list(
        bookings.exclude(pk__in=[b.pk for b in upcoming]).order_by("-start_at")[:PAST_LIMIT]
    )

    node = referral_tree.get_node(client)
    invited_by = None
    if node is not None and node.sponsor_id:
        sponsor = node.sponsor.user
        # Номер пригласившего — тоже персональные данные, и мастеру он ни к
        # чему: достаточно понять, «чей» это клиент.
        invited_by = {"name": sponsor.display_name, "phone": mask_phone(sponsor.phone)}

    return ClientCard(
        client=client,
        cars=list(cars_service.list_cars(client)),
        upcoming=upcoming,
        past=past,
        balance=node.balance if node else 0,
        max_discount_percent=settings.REFERRAL["MAX_DISCOUNT_PERCENT"],
        # Сколько можно списать — зависит от чека, поэтому считаем по
        # ближайшей записи: с ней клиент и приедет.
        next_quote=(
            {"booking": upcoming[0], **referral_points.spend_quote(upcoming[0])}
            if upcoming
            else None
        ),
        invited_by=invited_by,
        calls=calls_service.client_journal(staff, client.pk)[:CALLS_LIMIT],
    )
