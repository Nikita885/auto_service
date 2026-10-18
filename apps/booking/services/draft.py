"""Сценарий записи: черновик и его шаги.

Ключевое требование: как только клиент начал записываться, в базе появляется
объект состояния. По нему в любой момент видно, на каком шаге человек и что
уже выбрано — и это же состояние уходит в WebSocket.

Черновик живёт `BOOKING["DRAFT_TTL_SECONDS"]` секунд от старта. Таймер не
продлевается на шагах: иначе слот можно было бы удерживать бесконечно.
Протухший черновик закрывается и больше не принимает действий — клиент
начинает заново.

Вперёд шаги идут строго по порядку, а назад — на любой пройденный: клиент
передумал с адресом или услугой и не должен ради этого начинать заново и
терять таймер. Что зависит от изменённого, сбрасывается: другой адрес —
категория, услуга и время выбираются заново (на другой точке свой
каталог, свои остатки и своя сетка), другая категория — услуга заново,
другая услуга — время остаётся (сетка от услуги не зависит).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.booking import events
from apps.booking.constants import (
    LEGACY_STEPS,
    STEP_ORDER,
    DraftCloseReason,
    DraftStep,
)
from apps.booking.models import Booking, BookingDraft
from apps.booking.services import booking as booking_service
from apps.booking.services import slots as slots_service
from apps.booking.services import stock as stock_service
from apps.catalog.models import ServiceCategory, ServicePoint
from apps.common.exceptions import (
    ConflictError,
    GoneError,
    NotFoundError,
    ValidationError,
)
from apps.common.phone import mask_phone
from apps.garage.services import cars as cars_service

logger = logging.getLogger(__name__)


# --------------------------------------------------------------- служебное
def _close(draft: BookingDraft, step: DraftStep, reason: DraftCloseReason) -> None:
    draft.step = step
    draft.is_open = False
    draft.close_reason = reason
    draft.save(update_fields=["step", "is_open", "close_reason", "updated_at"])


def _expire(draft: BookingDraft) -> None:
    """Закрыть протухший черновик и сообщить клиенту."""
    _close(draft, DraftStep.EXPIRED, DraftCloseReason.EXPIRED)
    events.publish_draft(draft, events.DRAFT_EXPIRED)
    logger.info("Черновик %s истёк", draft.pk)


def get_open_draft(user) -> BookingDraft | None:
    """Текущий черновик клиента. Протухший гасится прямо здесь.

    Это делает состояние честным даже если Celery-beat лежит: клиент,
    который вернулся через час, увидит «истёк», а не «шаг 2 из 4».
    """
    draft = (
        BookingDraft.objects.open()
        .select_related("service_point", "service_category", "service")
        .filter(user=user)
        .first()
    )
    if draft is None:
        return None
    if draft.is_expired:
        _expire(draft)
        return None
    return draft


def _lock_draft(user, draft_id) -> BookingDraft:
    """Взять черновик под блокировку строки — шаги клиента сериализуются.

    `of=("self",)` обязателен: `select_related` по nullable FK даёт LEFT JOIN,
    а Postgres не умеет блокировать nullable-сторону внешнего соединения.
    Блокируем только строку черновика — она и есть предмет гонки.
    """
    try:
        draft = (
            BookingDraft.objects.select_for_update(of=("self",))
            .select_related("service_point", "service_category", "service")
            .get(pk=draft_id, user=user)
        )
    except BookingDraft.DoesNotExist as exc:
        raise NotFoundError("Черновик не найден", code="draft_not_found") from exc

    if not draft.is_open:
        raise GoneError(
            "Черновик закрыт, начните запись заново",
            code="draft_closed",
            details={"close_reason": draft.close_reason},
        )

    if draft.is_expired:
        _expire(draft)
        raise GoneError(
            "Время на запись истекло, начните заново", code="draft_expired"
        )

    return draft


def _require_step(draft: BookingDraft, expected: DraftStep) -> None:
    if draft.step != expected:
        raise ValidationError(
            "Шаг выполняется не по порядку",
            code="draft_wrong_step",
            details={"current_step": draft.step, "expected_step": expected},
        )


def _require_reached(draft: BookingDraft, reached: DraftStep) -> None:
    """Шаг доступен, если до него дошли: вперёд — по порядку, назад — любой."""
    current = LEGACY_STEPS.get(draft.step, draft.step)
    if STEP_ORDER.index(current) < STEP_ORDER.index(reached):
        _require_step(draft, reached)


def _touch(draft: BookingDraft, *fields: str) -> BookingDraft:
    draft.save(update_fields=[*fields, "step", "updated_at"])
    events.publish_draft(draft)
    return draft


# --------------------------------------------------------------- сценарий
@transaction.atomic
def start_draft(user, *, restart: bool = False) -> BookingDraft:
    """Начать запись.

    По умолчанию повторный вызов возвращает уже существующий живой черновик —
    так перезагрузка экрана не сбрасывает прогресс и не крадёт время таймера.
    `restart=True` явно выбрасывает старый черновик и начинает заново.
    """
    existing = (
        BookingDraft.objects.select_for_update().filter(user=user, is_open=True).first()
    )

    if existing and not existing.is_expired:
        if not restart:
            return existing
        _close(existing, DraftStep.CANCELLED, DraftCloseReason.RESTARTED)
    elif existing:
        _expire(existing)

    draft = BookingDraft.objects.create(
        user=user,
        step=DraftStep.STARTED,
        expires_at=timezone.now()
        + timedelta(seconds=settings.BOOKING["DRAFT_TTL_SECONDS"]),
    )
    transaction.on_commit(lambda: events.publish_draft(draft))
    logger.info(
        "Клиент %s начал запись, черновик %s", mask_phone(user.phone), draft.pk
    )
    return draft


@transaction.atomic
def select_point(user, draft_id, service_point_id) -> BookingDraft:
    draft = _lock_draft(user, draft_id)

    try:
        point = ServicePoint.objects.get(pk=service_point_id, is_active=True)
    except ServicePoint.DoesNotExist as exc:
        raise NotFoundError("Точка не найдена", code="point_not_found") from exc

    # Вернулся к адресу и выбрал тот же — дальше выбранное остаётся.
    if draft.service_point_id == point.pk and draft.step != DraftStep.STARTED:
        return draft

    # Другая точка: каталог, остатки и сетка времени у неё свои, поэтому
    # категория, услуга и время выбираются заново, а их резерв
    # освобождается сразу.
    draft.service_point = point
    draft.service_category = None
    draft.service = None
    draft.on_site = False
    draft.oil = None
    draft.oil_on_site = False
    draft.slot_start = None
    draft.step = DraftStep.POINT_SELECTED
    return _touch(
        draft, "service_point", "service_category", "service", "on_site",
        "oil", "oil_on_site", "slot_start",
    )


@transaction.atomic
def select_category(user, draft_id, category_id) -> BookingDraft:
    """Категория услуг: «Замена масла», «Замена резины», «Мойка».

    Другая категория — услуга выбирается заново: услуга из чужой
    категории в записи не окажется. Время остаётся за клиентом: сетка от
    категории не зависит.
    """
    draft = _lock_draft(user, draft_id)
    _require_reached(draft, DraftStep.POINT_SELECTED)

    category = stock_service.get_category(draft.service_point, category_id)
    same = draft.service_category_id == category.pk
    draft.service_category = category
    if not same:
        draft.service = None
        draft.on_site = False
        draft.oil = None
        draft.oil_on_site = False
        # Выбранное время за клиентом остаётся (сетка от категории не
        # зависит), но шаг откатывается: пока услуги нет, подтверждать
        # нечего, и `next_action` обязан сказать именно это.
        draft.step = DraftStep.CATEGORY_SELECTED
    elif draft.step in (DraftStep.STARTED, DraftStep.POINT_SELECTED):
        draft.step = DraftStep.CATEGORY_SELECTED
    return _touch(draft, "service_category", "service", "on_site", "oil", "oil_on_site")


@transaction.atomic
def select_service(
    user, draft_id, service_id=None, *, on_site: bool = False
) -> BookingDraft:
    """Услуга из категории или «подберите на месте» (`on_site`, без услуги).

    Время от услуги не зависит, поэтому, если клиент вернулся сменить
    услугу уже после выбора времени, время остаётся за ним.
    """
    draft = _lock_draft(user, draft_id)
    _require_reached(draft, DraftStep.CATEGORY_SELECTED)

    if on_site:
        if not draft.service_category.allow_on_site:
            raise ValidationError(
                "В этой категории нужно выбрать услугу", code="on_site_not_allowed"
            )
        draft.service = None
        draft.on_site = True
    else:
        service = stock_service.get_available_service(
            draft.service_point, service_id, exclude_draft_id=draft.pk
        )
        if service.category_id != draft.service_category_id:
            raise ValidationError(
                "Эта услуга из другой категории", code="service_other_category"
            )
        draft.service = service
        draft.on_site = False
    # Поля масла больше не читаются, но пока они есть — держим их в
    # согласии с выбором: откат кода не должен увидеть пустой черновик.
    draft.oil_id = draft.service.oil_id if draft.service_id else None
    draft.oil_on_site = draft.on_site

    # Время могло быть выбрано раньше — например, клиент вернулся сменить
    # категорию. Тогда шаг сразу «время выбрано»: заставлять выбирать его
    # заново незачем, оно всё это время за клиентом и держится.
    draft.step = (
        DraftStep.SLOT_SELECTED if draft.slot_start else DraftStep.SERVICE_SELECTED
    )
    return _touch(draft, "service", "on_site", "oil", "oil_on_site")


@transaction.atomic
def select_oil(user, draft_id, oil_id=None, *, on_site: bool = False) -> BookingDraft:
    """Тот же шаг по старому API: масло вместо категории и услуги.

    Остаётся рабочим, пока обновляются приложения. Категорию ставим ту, в
    которую перенесли это масло: приложению прежней версии её выбирать
    нечем. Коды ошибок остаются прежними (`oil_*`) — их разбирает ровно
    то приложение, которое мы и не хотим сломать.
    """
    from apps.catalog.services.oils import OIL_CATEGORY_NAME, service_for_oil

    draft = _lock_draft(user, draft_id)
    _require_reached(draft, DraftStep.POINT_SELECTED)

    if on_site:
        category = draft.service_category or ServiceCategory.objects.filter(
            service_point=draft.service_point, name=OIL_CATEGORY_NAME, is_active=True
        ).first()
        if category is None:
            raise NotFoundError(
                "На этой точке нет замены масла", code="oil_not_available"
            )
        select_category(user, draft_id, category.pk)
        return select_service(user, draft_id, on_site=True)

    service = service_for_oil(draft.service_point, oil_id)
    select_category(user, draft_id, service.category_id)
    try:
        return select_service(user, draft_id, service.pk)
    except ConflictError as exc:
        if exc.code != "service_out_of_stock":
            raise
        raise ConflictError(
            "Это масло только что разобрали, выберите другое",
            code="oil_out_of_stock",
        ) from exc


@transaction.atomic
def select_slot(user, draft_id, start_at: datetime) -> BookingDraft:
    draft = _lock_draft(user, draft_id)
    _require_reached(draft, DraftStep.SERVICE_SELECTED)

    # Блокируем точку: параллельные выборы одного слота выстраиваются в очередь.
    ServicePoint.objects.select_for_update().get(pk=draft.service_point_id)

    slot_start, _ = slots_service.validate_slot(
        draft.service_point, start_at, exclude_draft_id=draft.pk
    )

    draft.slot_start = slot_start
    draft.step = DraftStep.SLOT_SELECTED
    return _touch(draft, "slot_start")


@transaction.atomic
def confirm(user, draft_id, *, comment: str = "", car_id=None) -> Booking:
    """Финальный шаг: превратить черновик в запись.

    Все проверки повторяются здесь ещё раз. Между выбором времени и нажатием
    «Подтвердить» могло пройти четыре минуты, за которые слот заняли или
    услуга кончилась — узнать об этом клиент должен до, а не после.

    `car_id` — какую из своих машин клиент везёт; не передан — основная.
    Чужая или удалённая машина — `car_not_found`, черновик остаётся жив.
    """
    draft = _lock_draft(user, draft_id)
    _require_step(draft, DraftStep.SLOT_SELECTED)
    car = cars_service.car_for_booking(user, car_id)
    car_model, car_plate = cars_service.snapshot(car)

    has_service = draft.service_id or draft.on_site
    if not (draft.service_point_id and draft.service_category_id and has_service
            and draft.slot_start):
        raise ValidationError("Выбраны не все параметры", code="draft_incomplete")

    point = ServicePoint.objects.select_for_update().get(pk=draft.service_point_id)

    _, end_at = slots_service.validate_slot(
        point, draft.slot_start, exclude_draft_id=draft.pk
    )
    services = (
        [stock_service.get_available_service(
            point, draft.service_id, exclude_draft_id=draft.pk
        )]
        if draft.service_id
        else []
    )

    if Booking.objects.active().filter(user=user, start_at=draft.slot_start).exists():
        raise ConflictError(
            "У вас уже есть запись на это время", code="duplicate_booking"
        )

    draft.step = DraftStep.CONFIRMED
    draft.is_open = False
    draft.close_reason = DraftCloseReason.CONFIRMED
    # Колбэк ставится до создания записи, чтобы порядок событий остался
    # прежним: сначала «черновик закрыт», потом «запись создана».
    transaction.on_commit(lambda: events.publish_draft(draft, events.DRAFT_CLOSED))

    booking = booking_service.create_booking(
        user=user,
        point=point,
        category=draft.service_category,
        services=services,
        on_site=draft.on_site,
        start_at=draft.slot_start,
        end_at=end_at,
        client_name=user.full_name,
        car=car,
        car_model=car_model,
        car_plate=car_plate,
        comment=comment,
        actor=user,
        log_comment="Запись создана клиентом",
    )

    draft.booking = booking
    draft.save(
        update_fields=["booking", "step", "is_open", "close_reason", "updated_at"]
    )

    logger.info("Создана запись %s для %s", booking.code, mask_phone(user.phone))
    return booking


@transaction.atomic
def cancel_draft(user, draft_id) -> BookingDraft:
    """Клиент передумал до подтверждения — освобождаем слот немедленно."""
    draft = _lock_draft(user, draft_id)
    _close(draft, DraftStep.CANCELLED, DraftCloseReason.CANCELLED)
    transaction.on_commit(lambda: events.publish_draft(draft, events.DRAFT_CLOSED))
    return draft


def expire_stale_drafts(limit: int = 500) -> int:
    """Погасить черновики, у которых вышло время.

    Вызывается из Celery-beat. Не единственная защита: `get_open_draft` и
    `_lock_draft` тоже проверяют срок, так что запись не «оживёт», даже если
    воркер упал.
    """
    stale = list(
        BookingDraft.objects.stale().select_related(
            "user", "service_point", "service"
        )[:limit]
    )
    for draft in stale:
        with transaction.atomic():
            locked = (
                BookingDraft.objects.select_for_update()
                .filter(pk=draft.pk, is_open=True)
                .first()
            )
            if locked is None:
                continue
            _expire(locked)
    return len(stale)
