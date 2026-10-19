from django.db import models


class DraftStep(models.TextChoices):
    """Шаги мастера записи.

    Порядок жёсткий: адрес -> категория -> услуга -> время ->
    подтверждение. Клиент не может перепрыгнуть шаг, потому что список
    категорий зависит от точки, список услуг — от категории, а свободные
    слоты — от точки и загрузки постов.
    """

    STARTED = "started", "Начата"
    POINT_SELECTED = "point_selected", "Выбран адрес"
    CATEGORY_SELECTED = "category_selected", "Выбрана категория"
    SERVICE_SELECTED = "service_selected", "Выбрана услуга"
    # Шаг из времени, когда услуга была одна — замена масла. Остаётся в
    # перечислении ради закрытых черновиков: по ним считается воронка
    # записи, и переписывать историю ради красоты списка нельзя.
    OIL_SELECTED = "oil_selected", "Выбрано масло (устарело)"
    SLOT_SELECTED = "slot_selected", "Выбрано время"
    CONFIRMED = "confirmed", "Подтверждена"
    EXPIRED = "expired", "Истекла"
    CANCELLED = "cancelled", "Отменена клиентом"


#: Шаги, на которых черновик ещё живой и его можно двигать дальше.
OPEN_DRAFT_STEPS = frozenset(
    {
        DraftStep.STARTED,
        DraftStep.POINT_SELECTED,
        DraftStep.CATEGORY_SELECTED,
        DraftStep.SERVICE_SELECTED,
        DraftStep.SLOT_SELECTED,
    }
)

#: Какой шаг обязан быть достигнут, чтобы перейти к следующему действию.
STEP_ORDER = [
    DraftStep.STARTED,
    DraftStep.POINT_SELECTED,
    DraftStep.CATEGORY_SELECTED,
    DraftStep.SERVICE_SELECTED,
    DraftStep.SLOT_SELECTED,
]

#: Что клиент должен сделать дальше — отдаём прямо в API, чтобы UI не гадал.
NEXT_ACTION = {
    DraftStep.STARTED: "select_point",
    DraftStep.POINT_SELECTED: "select_category",
    DraftStep.CATEGORY_SELECTED: "select_service",
    DraftStep.SERVICE_SELECTED: "select_slot",
    # Черновик, который был на шаге масла в момент выкатки, живёт ещё до
    # пяти минут. Для него шаг масла равен шагу услуги — иначе он падал бы
    # с 500 на первом же действии клиента.
    DraftStep.OIL_SELECTED: "select_slot",
    DraftStep.SLOT_SELECTED: "confirm",
}

#: Устаревший шаг → его замена в порядке шагов.
LEGACY_STEPS = {DraftStep.OIL_SELECTED: DraftStep.SERVICE_SELECTED}


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


class CallOutcome(models.TextChoices):
    """Чем закончился звонок мастера клиенту."""

    REACHED = "reached", "Дозвонился"
    NO_ANSWER = "no_answer", "Не дозвонился"
    CALLBACK = "callback", "Перезвонить"


class CallReason(models.TextChoices):
    """Зачем звонить. Порядок перечисления — порядок очереди (решение
    заказчика): первыми — скорая запись, где услугу ещё не выбрали."""

    ON_SITE = "on_site", "Подобрать услугу"
    CALLBACK = "callback", "Перезвонить"
    LATE = "late", "Опаздывает"
    TOMORROW = "tomorrow", "Запись на завтра"
    OFF_HOURS = "off_hours", "Запись вне рабочих часов"
    NO_SHOW = "no_show", "Не приехал"
    OTHER = "other", "Другое"


#: Приоритет причины в очереди «Кому позвонить»: меньше — выше.
CALL_PRIORITY = {reason: index for index, reason in enumerate(CallReason.values)}
