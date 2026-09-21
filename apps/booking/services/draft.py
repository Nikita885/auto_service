"""Сценарий записи: черновик и его шаги.

Ключевое требование: как только клиент начал записываться, в базе появляется
объект состояния. По нему в любой момент видно, на каком шаге человек и что
уже выбрано — и это же состояние уходит в WebSocket.

Черновик живёт `BOOKING["DRAFT_TTL_SECONDS"]` секунд от старта. Таймер не
продлевается на шагах: иначе слот можно было бы удерживать бесконечно.
Протухший черновик закрывается и больше не принимает действий — клиент
начинает заново.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.booking import events
from apps.booking.constants import (
    BookingStatus,
    DraftCloseReason,
    DraftStep,
)
from apps.booking.models import Booking, BookingDraft, BookingStatusLog
from apps.booking.services import slots as slots_service
from apps.booking.services import stock as stock_service
from apps.catalog.models import ServicePoint
from apps.common.exceptions import (
    ConflictError,
    GoneError,
    NotFoundError,
    ValidationError,
)
from apps.common.phone import mask_phone

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
        .select_related("service_point", "oil")
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
            .select_related("service_point", "oil")
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
    _require_step(draft, DraftStep.STARTED)

    try:
        point = ServicePoint.objects.get(pk=service_point_id, is_active=True)
    except ServicePoint.DoesNotExist as exc:
        raise NotFoundError("Точка не найдена", code="point_not_found") from exc

    draft.service_point = point
    draft.step = DraftStep.POINT_SELECTED
    return _touch(draft, "service_point")


@transaction.atomic
def select_oil(user, draft_id, oil_id) -> BookingDraft:
    draft = _lock_draft(user, draft_id)
    _require_step(draft, DraftStep.POINT_SELECTED)

    oil = stock_service.get_available_oil(
        draft.service_point, oil_id, exclude_draft_id=draft.pk
    )

    draft.oil = oil
    draft.step = DraftStep.OIL_SELECTED
    return _touch(draft, "oil")


@transaction.atomic
def select_slot(user, draft_id, start_at: datetime) -> BookingDraft:
    draft = _lock_draft(user, draft_id)
    _require_step(draft, DraftStep.OIL_SELECTED)

    # Блокируем точку: параллельные выборы одного слота выстраиваются в очередь.
    ServicePoint.objects.select_for_update().get(pk=draft.service_point_id)

    slot_start, _ = slots_service.validate_slot(
        draft.service_point, start_at, exclude_draft_id=draft.pk
    )

    draft.slot_start = slot_start
    draft.step = DraftStep.SLOT_SELECTED
    return _touch(draft, "slot_start")


@transaction.atomic
def confirm(user, draft_id, *, comment: str = "") -> Booking:
    """Финальный шаг: превратить черновик в запись.

    Все проверки повторяются здесь ещё раз. Между выбором времени и нажатием
    «Подтвердить» могло пройти четыре минуты, за которые слот заняли или
    масло закончилось — узнать об этом клиент должен до, а не после.
    """
    draft = _lock_draft(user, draft_id)
    _require_step(draft, DraftStep.SLOT_SELECTED)

    if not (draft.service_point_id and draft.oil_id and draft.slot_start):
        raise ValidationError("Выбраны не все параметры", code="draft_incomplete")

    point = ServicePoint.objects.select_for_update().get(pk=draft.service_point_id)

    _, end_at = slots_service.validate_slot(
        point, draft.slot_start, exclude_draft_id=draft.pk
    )
    oil = stock_service.get_available_oil(
        point, draft.oil_id, exclude_draft_id=draft.pk
    )

    if Booking.objects.active().filter(user=user, start_at=draft.slot_start).exists():
        raise ConflictError(
            "У вас уже есть запись на это время", code="duplicate_booking"
        )

    booking = Booking.objects.create(
        user=user,
        service_point=point,
        oil=oil,
        start_at=draft.slot_start,
        end_at=end_at,
        status=BookingStatus.PENDING,
        client_name=user.full_name,
        client_phone=user.phone,
        car_model=user.car_model,
        car_plate=user.car_plate,
        oil_title=str(oil),
        oil_price=oil.price,
        work_price=oil.work_price,
        total_price=oil.total_price,
        client_comment=comment or "",
    )
    BookingStatusLog.objects.create(
        booking=booking,
        from_status="",
        to_status=BookingStatus.PENDING,
        actor=user,
        comment="Запись создана клиентом",
    )

    draft.booking = booking
    draft.step = DraftStep.CONFIRMED
    draft.is_open = False
    draft.close_reason = DraftCloseReason.CONFIRMED
    draft.save(
        update_fields=["booking", "step", "is_open", "close_reason", "updated_at"]
    )

    def _after_commit() -> None:
        from apps.notifications.services import notify_booking_created

        events.publish_draft(draft, events.DRAFT_CLOSED)
        events.publish_booking(booking, events.BOOKING_CREATED)
        notify_booking_created(booking)

    transaction.on_commit(_after_commit)
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
        BookingDraft.objects.stale().select_related("user", "service_point", "oil")[:limit]
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
