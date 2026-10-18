from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from apps.booking.constants import (
    ACTIVE_BOOKING_STATUSES,
    NEXT_ACTION,
    OPEN_DRAFT_STEPS,
    BookingStatus,
    DraftCloseReason,
    DraftStep,
)
from apps.common.codes import generate_code
from apps.common.models import BaseModel


def generate_booking_code() -> str:
    """Короткий человекочитаемый код записи: клиент называет его на посту.

    Обёртка, а не прямая ссылка на `generate_code`: имя функции записано в
    миграции как значение `default`, и переезд сломал бы её.
    """
    return generate_code(6)


class BookingDraftQuerySet(models.QuerySet):
    def open(self):
        return self.filter(is_open=True)

    def alive(self):
        """Открытые и ещё не протухшие. Именно они держат слот и канистру."""
        return self.open().filter(expires_at__gt=timezone.now())

    def stale(self):
        return self.open().filter(expires_at__lte=timezone.now())


class BookingDraft(BaseModel):
    """Черновик записи — состояние процесса, а не сама запись.

    Создаётся в момент, когда клиент нажал «Записаться», и живёт ровно
    `BOOKING["DRAFT_TTL_SECONDS"]` (по ТЗ — 5 минут) с этого момента. Часы
    не сбрасываются на шагах: иначе можно было бы держать слот вечно,
    перещёлкивая масло.

    Пока черновик жив, он резервирует выбранный слот и канистру масла —
    поэтому два человека не выберут последнее время одновременно.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="booking_drafts",
        verbose_name="клиент",
    )
    step = models.CharField(
        "шаг", max_length=20, choices=DraftStep.choices, default=DraftStep.STARTED
    )
    is_open = models.BooleanField("активен", default=True)
    close_reason = models.CharField(
        "причина закрытия",
        max_length=20,
        choices=DraftCloseReason.choices,
        blank=True,
    )

    service_point = models.ForeignKey(
        "catalog.ServicePoint",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drafts",
        verbose_name="точка",
    )
    oil = models.ForeignKey(
        "catalog.Oil",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drafts",
        verbose_name="масло",
    )
    # «Не знаю, какое нужно — подберите на месте»: шаг масла пройден без
    # масла. Мастер точки перезванивает и выбирает его вместе с клиентом
    # (решение заказчика, октябрь 2026). Отдельный флаг, а не пустой `oil`:
    # пустое масло значит ещё и «до этого шага не дошли».
    oil_on_site = models.BooleanField("масло подберут на месте", default=False)

    # Услуги по категориям: клиент выбирает сначала категорию, потом
    # услугу внутри неё. Поля масла выше остаются, пока обновляются
    # приложения, и больше не читаются — удалим их отдельной выкаткой.
    service_category = models.ForeignKey(
        "catalog.ServiceCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drafts",
        verbose_name="категория услуги",
    )
    service = models.ForeignKey(
        "catalog.Service",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drafts",
        verbose_name="услуга",
    )
    # «Не знаю, что нужно — подберите на месте»: шаг услуги пройден без
    # услуги. Отдельный флаг, а не пустая ссылка: пустая значит ещё и
    # «до этого шага не дошли».
    on_site = models.BooleanField("услугу подберут на месте", default=False)

    slot_start = models.DateTimeField("начало слота", null=True, blank=True)

    expires_at = models.DateTimeField("истекает", db_index=True)
    booking = models.OneToOneField(
        "booking.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="draft",
        verbose_name="итоговая запись",
    )

    objects = BookingDraftQuerySet.as_manager()

    class Meta:
        verbose_name = "черновик записи"
        verbose_name_plural = "черновики записей"
        ordering = ["-created_at"]
        constraints = [
            # У клиента может быть только один живой черновик. Начал заново —
            # старый обязан быть закрыт в той же транзакции.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_open=True),
                name="uniq_open_draft_per_user",
            )
        ]
        indexes = [
            models.Index(fields=["service_point", "slot_start", "is_open"]),
            models.Index(fields=["is_open", "expires_at"]),
            # Доступность услуги считается по живым черновикам, которые её
            # держат: без индекса это перебор всех черновиков на каждый
            # показ списка услуг.
            models.Index(fields=["service", "is_open"]),
        ]

    def __str__(self) -> str:
        return f"Черновик {self.user.phone} [{self.step}]"

    # ------------------------------------------------------------ состояние
    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_alive(self) -> bool:
        return self.is_open and not self.is_expired

    @property
    def seconds_left(self) -> int:
        return max(int((self.expires_at - timezone.now()).total_seconds()), 0)

    @property
    def next_action(self) -> str | None:
        return NEXT_ACTION.get(self.step)

    @property
    def slot_end(self):
        if not (self.slot_start and self.service_point):
            return None
        return self.slot_start + timedelta(minutes=self.service_point.slot_minutes)

    def selected_summary(self) -> dict:
        """Что уже выбрано. Ровно это уходит в WebSocket и в GET черновика."""
        return {
            "service_point": str(self.service_point_id) if self.service_point_id else None,
            "oil": str(self.oil_id) if self.oil_id else None,
            "slot_start": self.slot_start.isoformat() if self.slot_start else None,
        }

    def can_move(self) -> bool:
        return self.is_open and self.step in OPEN_DRAFT_STEPS and not self.is_expired


class BookingQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status__in=ACTIVE_BOOKING_STATUSES)

    def upcoming(self):
        return self.active().filter(start_at__gte=timezone.now())

    def for_user(self, user):
        return self.filter(user=user)


class Booking(BaseModel):
    """Подтверждённая запись на замену масла.

    Часть полей продублирована из профиля и каталога (`client_name`,
    `oil_title`, цены). Это снимок на момент брони: если завтра масло
    подорожает или клиент сменит машину, история записи не должна поехать.
    """

    code = models.CharField(
        "код записи", max_length=8, unique=True, default=generate_booking_code
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bookings",
        verbose_name="клиент",
    )
    service_point = models.ForeignKey(
        "catalog.ServicePoint",
        on_delete=models.PROTECT,
        related_name="bookings",
        verbose_name="точка",
    )
    # Пусто — клиент попросил подобрать масло на месте: запись стоит в
    # очереди звонков у мастера, пока он не выберет масло
    # (`booking.set_oil`). Выполнить запись без масла нельзя — со склада
    # списывается конкретная канистра.
    oil = models.ForeignKey(
        "catalog.Oil",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bookings",
        verbose_name="масло",
    )
    # Категория услуги записи. У записи «подберут на месте» она —
    # единственное, что известно: мастер перезванивает и выбирает услугу
    # внутри неё. Сами услуги лежат позициями (`BookingItem`).
    service_category = models.ForeignKey(
        "catalog.ServiceCategory",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bookings",
        verbose_name="категория услуги",
    )
    # Услугу подберёт мастер после звонка. Не выводится из «нет позиций»:
    # позиций нет и у записи, которую только что создали, а разница между
    # «ещё не выбрали» и «выбирать будет мастер» видна в очереди звонков.
    service_on_site = models.BooleanField(
        "услугу подберут на месте", default=False
    )
    # Какую машину обслуживали. Ссылка — для гаража и истории по машине;
    # что показывать, решает снимок `car_model`/`car_plate` ниже: клиент
    # может переименовать или удалить машину, а запись не должна поехать.
    car = models.ForeignKey(
        "garage.Car",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
        verbose_name="автомобиль",
    )

    start_at = models.DateTimeField("начало", db_index=True)
    end_at = models.DateTimeField("окончание")
    status = models.CharField(
        "статус",
        max_length=24,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING,
        db_index=True,
    )

    # --- снимок данных на момент брони
    client_name = models.CharField("имя клиента", max_length=150, blank=True)
    client_phone = models.CharField("телефон клиента", max_length=20)
    car_model = models.CharField("автомобиль", max_length=120, blank=True)
    car_plate = models.CharField("госномер", max_length=16, blank=True)
    oil_title = models.CharField("масло (снимок)", max_length=255)
    oil_price = models.DecimalField("цена масла", max_digits=10, decimal_places=2)
    category_title = models.CharField("категория (снимок)", max_length=120, blank=True)
    service_title = models.CharField("услуги (снимок)", max_length=255, blank=True)
    # Сколько из итога ушло на расходники — сумма материалов позиций.
    # Нужна метрикам: доля материала и доля работы в выручке.
    material_price = models.DecimalField(
        "материал", max_digits=10, decimal_places=2, default=0
    )
    work_price = models.DecimalField("цена работ", max_digits=10, decimal_places=2)
    total_price = models.DecimalField("итого", max_digits=10, decimal_places=2)
    # Сколько чека клиент закрыл баллами при расчёте. Решает клиент, вводит
    # мастер при завершении; в журнале баллов этому соответствует списание.
    points_spent = models.DecimalField(
        "оплачено баллами", max_digits=10, decimal_places=2, default=0
    )
    # Итог, если мастер поправил его при расчёте: долил масла, добавил
    # работу или уступил. Цены выше не трогаем — это то, о чём договорились
    # при записи, и по ним видно, откуда взялась разница. Пусто — итог равен
    # снимку; кто и почему менял — в `BookingPriceChange`.
    final_price = models.DecimalField(
        "итог при расчёте", max_digits=10, decimal_places=2, null=True, blank=True
    )

    # --- сопровождение
    master = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="served_bookings",
        verbose_name="мастер",
    )
    client_comment = models.CharField("комментарий клиента", max_length=500, blank=True)
    cancel_reason = models.CharField("причина отмены", max_length=500, blank=True)
    cancelled_at = models.DateTimeField("отменена", null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_bookings",
        verbose_name="кто отменил",
    )
    reminder_sent_at = models.DateTimeField("напоминание отправлено", null=True, blank=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        verbose_name = "запись"
        verbose_name_plural = "записи"
        ordering = ["-start_at"]
        constraints = [
            # Один клиент не может дважды занять один и тот же слот.
            models.UniqueConstraint(
                fields=["user", "start_at"],
                # sorted() — чтобы миграция была детерминированной.
                condition=models.Q(status__in=sorted(ACTIVE_BOOKING_STATUSES)),
                name="uniq_active_booking_per_user_slot",
            )
        ]
        indexes = [
            models.Index(fields=["service_point", "start_at", "status"]),
            models.Index(fields=["user", "-start_at"]),
            models.Index(fields=["status", "start_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.code}: {self.client_phone} на {self.start_at:%d.%m %H:%M}"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_BOOKING_STATUSES

    @property
    def charged_price(self):
        """Чек к оплате: итог мастера, а если его не правили — цена брони."""
        return self.total_price if self.final_price is None else self.final_price

    @property
    def paid_amount(self):
        """Сколько клиент заплатил деньгами: чек минус баллы."""
        return self.charged_price - self.points_spent

    @property
    def is_cancellable_by_client(self) -> bool:
        """Отменять «за минуту до» нельзя — пост уже держат под клиента."""
        if self.status != BookingStatus.PENDING:
            return False
        deadline = self.start_at - timedelta(
            minutes=settings.BOOKING["CANCEL_DEADLINE_MINUTES"]
        )
        return timezone.now() < deadline

    def local_start(self):
        return self.start_at.astimezone(self.service_point.tz)


class BookingItem(BaseModel):
    """Услуга в записи — позиция чека.

    Таблица позиций, а не одна ссылка в записи: в одной записи может быть
    несколько услуг (решение заказчика). Пока интерфейс выбирает одну,
    но история и деньги уже лежат позициями — иначе «несколько» однажды
    потребовало бы второй миграции данных на живой базе.

    Цены — снимок на момент записи: прайс поменяется, а чек не поедет.
    Ссылка на услугу — `PROTECT`: выключить услугу можно, а удалить ту,
    по которой кого-то обслужили, нельзя, иначе история опустеет.
    """

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="items", verbose_name="запись"
    )
    service = models.ForeignKey(
        "catalog.Service",
        on_delete=models.PROTECT,
        related_name="booking_items",
        verbose_name="услуга",
    )
    title = models.CharField("услуга (снимок)", max_length=255)
    category_title = models.CharField("категория (снимок)", max_length=120, blank=True)
    price = models.DecimalField("цена", max_digits=10, decimal_places=2)
    material_price = models.DecimalField(
        "из них материал", max_digits=10, decimal_places=2, default=0
    )
    quantity = models.PositiveSmallIntegerField(
        "количество", default=1, validators=[MinValueValidator(1)]
    )

    class Meta:
        verbose_name = "услуга записи"
        verbose_name_plural = "услуги записи"
        # По возрастанию создания: позиции читаются в том порядке, в
        # котором их выбирали, и чек не перетасовывается между показами.
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(material_price__lte=models.F("price")),
                name="item_material_not_above_price",
            )
        ]

    def __str__(self) -> str:
        return f"{self.title} x{self.quantity}"

    @property
    def total(self):
        """Сумма позиции: цена за единицу на количество."""
        return self.price * self.quantity

    @property
    def work_price(self):
        return (self.price - self.material_price) * self.quantity


class BookingStatusLog(BaseModel):
    """История смены статусов. Нужна и для разбора спорных ситуаций,
    и для аналитики (сколько отмен, сколько неявок)."""

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="status_logs",
        verbose_name="запись",
    )
    from_status = models.CharField("из статуса", max_length=24, blank=True)
    to_status = models.CharField("в статус", max_length=24)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booking_status_changes",
        verbose_name="кто изменил",
    )
    comment = models.CharField("комментарий", max_length=500, blank=True)

    class Meta:
        verbose_name = "смена статуса"
        verbose_name_plural = "история статусов"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.booking_id}: {self.from_status} -> {self.to_status}"


class BookingPriceChange(BaseModel):
    """Мастер изменил итог при расчёте: кто, когда, с чего на что и почему.

    Отдельной таблицей, а не строкой в истории статусов: сумма — это деньги,
    и спорить о ней будут по числам, а не по тексту комментария.
    """

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="price_changes",
        verbose_name="запись",
    )
    old_price = models.DecimalField("было", max_digits=10, decimal_places=2)
    new_price = models.DecimalField("стало", max_digits=10, decimal_places=2)
    reason = models.CharField("причина", max_length=500, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booking_price_changes",
        verbose_name="кто изменил",
    )

    class Meta:
        verbose_name = "изменение итога"
        verbose_name_plural = "изменения итога"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.booking_id}: {self.old_price} -> {self.new_price}"
