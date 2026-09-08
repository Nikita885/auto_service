from django.db import models


class DraftStep(models.TextChoices):
    """Шаги мастера записи.

    Порядок жёсткий: адрес -> масло -> время -> подтверждение.
    Клиент не может перепрыгнуть шаг, потому что список масел зависит от
    точки, а свободные слоты — от точки и загрузки постов.
    """

    STARTED = "started", "Начата"
    POINT_SELECTED = "point_selected", "Выбран адрес"
    OIL_SELECTED = "oil_selected", "Выбрано масло"
    SLOT_SELECTED = "slot_selected", "Выбрано время"
    CONFIRMED = "confirmed", "Подтверждена"
    EXPIRED = "expired", "Истекла"
    CANCELLED = "cancelled", "Отменена клиентом"


#: Шаги, на которых черновик ещё живой и его можно двигать дальше.
OPEN_DRAFT_STEPS = frozenset(
    {
        DraftStep.STARTED,
        DraftStep.POINT_SELECTED,
        DraftStep.OIL_SELECTED,
        DraftStep.SLOT_SELECTED,
    }
)

#: Какой шаг обязан быть достигнут, чтобы перейти к следующему действию.
STEP_ORDER = [
    DraftStep.STARTED,
    DraftStep.POINT_SELECTED,
    DraftStep.OIL_SELECTED,
    DraftStep.SLOT_SELECTED,
]

#: Что клиент должен сделать дальше — отдаём прямо в API, чтобы UI не гадал.
NEXT_ACTION = {
    DraftStep.STARTED: "select_point",
    DraftStep.POINT_SELECTED: "select_oil",
    DraftStep.OIL_SELECTED: "select_slot",
    DraftStep.SLOT_SELECTED: "confirm",
}


class BookingStatus(models.TextChoices):
    PENDING = "pending", "Ожидает"
    IN_PROGRESS = "in_progress", "В работе"
    COMPLETED = "completed", "Выполнена"
    CANCELLED_BY_CLIENT = "cancelled_by_client", "Отменена клиентом"
    CANCELLED_BY_MASTER = "cancelled_by_master", "Отменена сервисом"
    NO_SHOW = "no_show", "Клиент не приехал"


#: Статусы, при которых запись занимает пост и канистру масла.
ACTIVE_BOOKING_STATUSES = frozenset(
    {BookingStatus.PENDING, BookingStatus.IN_PROGRESS}
)

#: Статусы, из которых уже никуда нельзя перейти.
FINAL_BOOKING_STATUSES = frozenset(
    {
        BookingStatus.COMPLETED,
        BookingStatus.CANCELLED_BY_CLIENT,
        BookingStatus.CANCELLED_BY_MASTER,
        BookingStatus.NO_SHOW,
    }
)


class DraftCloseReason(models.TextChoices):
    CONFIRMED = "confirmed", "Запись подтверждена"
    EXPIRED = "expired", "Истекло время"
    CANCELLED = "cancelled", "Отменена клиентом"
    RESTARTED = "restarted", "Начата заново"
