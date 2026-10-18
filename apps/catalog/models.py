from __future__ import annotations

import logging
import zoneinfo
from datetime import date, datetime, time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import BaseModel
from apps.common.translit import search_index as build_search_index

logger = logging.getLogger(__name__)

#: Часовые пояса России — выбор из списка, а не свободная строка. Свободную
#: строку однажды заполнили «Yekaterinburg Time» (так пояс зовёт Windows),
#: и расчёт свободного времени падал с 500 на каждом запросе.
RUSSIAN_TIMEZONES = [
    ("Europe/Kaliningrad", "Калининград (UTC+2)"),
    ("Europe/Moscow", "Москва, Санкт-Петербург (UTC+3)"),
    ("Europe/Samara", "Самара, Ижевск (UTC+4)"),
    ("Asia/Yekaterinburg", "Екатеринбург, Челябинск, Тюмень, Уфа, Пермь (UTC+5)"),
    ("Asia/Omsk", "Омск (UTC+6)"),
    ("Asia/Novosibirsk", "Новосибирск (UTC+7)"),
    ("Asia/Krasnoyarsk", "Красноярск, Кемерово (UTC+7)"),
    ("Asia/Irkutsk", "Иркутск (UTC+8)"),
    ("Asia/Yakutsk", "Якутск, Чита (UTC+9)"),
    ("Asia/Vladivostok", "Владивосток, Хабаровск (UTC+10)"),
    ("Asia/Magadan", "Магадан, Сахалин (UTC+11)"),
    ("Asia/Kamchatka", "Камчатка (UTC+12)"),
]

#: Как пояс пишут люди и Windows → имя, которое понимает система.
_TIMEZONE_ALIASES = {
    "yekaterinburg": "Asia/Yekaterinburg",
    "екатеринбург": "Asia/Yekaterinburg",
    "chelyabinsk": "Asia/Yekaterinburg",
    "челябинск": "Asia/Yekaterinburg",
    "moscow": "Europe/Moscow",
    "russian standard": "Europe/Moscow",
    "москва": "Europe/Moscow",
}


def normalize_timezone(value: str) -> str | None:
    """Имя пояса, понятное системе, или None, если не удалось угадать."""
    raw = (value or "").strip()
    try:
        zoneinfo.ZoneInfo(raw)
        return raw
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        pass
    lowered = raw.lower()
    for key, name in _TIMEZONE_ALIASES.items():
        if key in lowered:
            return name
    return None


def validate_timezone(value: str) -> None:
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(
            "Неизвестный часовой пояс. Для Челябинска и Екатеринбурга — Asia/Yekaterinburg."
        ) from exc


def validate_workdays(value) -> None:
    """Рабочие дни — список чисел 0–6 (0 = понедельник). Пустой — каждый день."""
    if not isinstance(value, list) or not all(
        isinstance(day, int) and not isinstance(day, bool) and 0 <= day <= 6 for day in value
    ):
        raise ValidationError(
            "Рабочие дни — список чисел от 0 (понедельник) до 6 (воскресенье), "
            "например [0, 1, 2, 3, 4]. Пустой список — каждый день."
        )


class OilType(models.TextChoices):
    SYNTHETIC = "synthetic", "Синтетическое"
    SEMI_SYNTHETIC = "semi_synthetic", "Полусинтетическое"
    MINERAL = "mineral", "Минеральное"


class ServicePoint(BaseModel):
    """Точка обслуживания (адрес). Сейчас их две, но модель это не ограничивает.

    График и пропускная способность лежат прямо здесь: расписание слотов
    считается на лету из этих полей, отдельной таблицы слотов нет —
    иначе пришлось бы генерировать её вперёд и чистить.
    """

    name = models.CharField("название", max_length=120)
    address = models.CharField("адрес", max_length=255)
    phone = models.CharField("телефон", max_length=20, blank=True)
    latitude = models.DecimalField(
        "широта", max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        "долгота", max_digits=9, decimal_places=6, null=True, blank=True
    )

    timezone = models.CharField(
        "часовой пояс",
        max_length=64,
        default="Europe/Moscow",
        choices=RUSSIAN_TIMEZONES,
        validators=[validate_timezone],
    )
    opens_at = models.TimeField("открытие", default=time(9, 0))
    closes_at = models.TimeField("закрытие", default=time(21, 0))
    workdays = models.JSONField(
        "рабочие дни",
        default=list,
        blank=True,
        validators=[validate_workdays],
        help_text="Дни недели, 0 = понедельник. Пустой список = работает всегда.",
    )
    slot_minutes = models.PositiveSmallIntegerField(
        "длительность слота, мин",
        default=30,
        validators=[MinValueValidator(5)],
    )
    posts_count = models.PositiveSmallIntegerField(
        "постов",
        default=2,
        validators=[MinValueValidator(1)],
        help_text="Сколько машин обслуживается одновременно — ёмкость одного слота.",
    )

    is_active = models.BooleanField("активна", default=True)

    class Meta:
        verbose_name = "точка обслуживания"
        verbose_name_plural = "точки обслуживания"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} — {self.address}"

    @property
    def tz(self) -> zoneinfo.ZoneInfo:
        """Пояс точки. Испорченное значение не должно ронять запись.

        Админка и миграция не пускают неверный пояс, но данные могли
        попасть в базу раньше. Лучше угадать пояс по названию (или взять
        пояс сети) и написать ошибку в лог, чем отдавать 500 на выборе
        времени, — `security_audit` покажет такую точку отдельно.
        """
        name = normalize_timezone(self.timezone)
        if name != self.timezone:
            logger.error("Точка %s: неверный часовой пояс %r", self.pk, self.timezone)
        return zoneinfo.ZoneInfo(name or settings.BUSINESS_TIMEZONE)

    def is_workday(self, day: date) -> bool:
        workdays = self.workdays
        if not isinstance(workdays, list):
            # Испорченное значение (например, число) — считаем, что точка
            # работает каждый день: закрыть запись целиком хуже.
            logger.error("Точка %s: неверные рабочие дни %r", self.pk, workdays)
            return True
        if not workdays:
            return True
        return day.weekday() in workdays

    def local_datetime(self, day: date, moment: time) -> datetime:
        """Локальное aware-время точки для указанных даты и времени."""
        return datetime.combine(day, moment, tzinfo=self.tz)


class Oil(BaseModel):
    """Позиция масла. Цена и объём фиксируются в записи на момент брони."""

    brand = models.CharField("бренд", max_length=80)
    name = models.CharField("название", max_length=120)
    viscosity = models.CharField("вязкость", max_length=16, help_text="Например, 5W-30")
    oil_type = models.CharField(
        "тип", max_length=20, choices=OilType.choices, default=OilType.SYNTHETIC
    )
    volume_liters = models.DecimalField(
        "объём канистры, л", max_digits=4, decimal_places=1, default=4
    )
    price = models.DecimalField("цена за канистру, ₽", max_digits=10, decimal_places=2)
    work_price = models.DecimalField(
        "стоимость работ, ₽", max_digits=10, decimal_places=2, default=0
    )
    description = models.TextField("описание", blank=True)
    is_active = models.BooleanField("в продаже", default=True)

    class Meta:
        verbose_name = "масло"
        verbose_name_plural = "масла"
        ordering = ["brand", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "name", "viscosity", "volume_liters"],
                name="uniq_oil_sku",
            )
        ]

    def __str__(self) -> str:
        return f"{self.brand} {self.name} {self.viscosity}, {self.volume_liters} л"

    @property
    def total_price(self):
        return self.price + self.work_price


class OilStock(BaseModel):
    """Остаток масла на конкретной точке.

    `quantity` — физический остаток в канистрах. Записи его не уменьшают:
    доступность считается как остаток минус активные брони и черновики.
    Списание происходит один раз, при завершении работ.
    """

    service_point = models.ForeignKey(
        ServicePoint, on_delete=models.CASCADE, related_name="stocks",
        verbose_name="точка",
    )
    oil = models.ForeignKey(
        Oil, on_delete=models.CASCADE, related_name="stocks", verbose_name="масло"
    )
    quantity = models.PositiveIntegerField("остаток, канистр", default=0)

    class Meta:
        verbose_name = "остаток масла"
        verbose_name_plural = "остатки масла"
        constraints = [
            models.UniqueConstraint(
                fields=["service_point", "oil"], name="uniq_stock_per_point"
            )
        ]
        indexes = [models.Index(fields=["service_point", "oil"])]

    def __str__(self) -> str:
        return f"{self.oil} @ {self.service_point.name}: {self.quantity} шт."


class ServiceJournalKind(models.TextChoices):
    """Чем выполненная запись станет в дневнике водителя.

    Значения совпадают с `garage.EntryKind`: дневник и напоминания
    считаются по ним. Перечисление повторено здесь, а не импортировано:
    `garage` зависит от `catalog` (машина ссылается на справочник марок),
    и обратный импорт замкнул бы приложения друг на друга. Совпадение
    значений держит тест `tests/test_services.py`.
    """

    OIL = "oil", "Замена масла"
    TIRES = "tires", "Шиномонтаж"
    WASH = "wash", "Мойка"
    SERVICE = "service", "ТО и ремонт"
    OTHER = "other", "Другое"


class ServiceCategory(BaseModel):
    """Категория услуг одной точки: «Замена масла», «Замена резины», «Мойка».

    Каталог у каждой точки свой (решение заказчика, октябрь 2026): у
    адресов разный набор работ и свои цены, а мастер ведёт только свою
    точку. Цена этого решения — одно и то же масло заводится на каждой
    точке отдельно; зато ни одна правка на одном адресе не меняет
    прайс другого.
    """

    service_point = models.ForeignKey(
        ServicePoint,
        on_delete=models.CASCADE,
        related_name="service_categories",
        verbose_name="точка",
    )
    name = models.CharField("название", max_length=120)
    sort_order = models.PositiveSmallIntegerField("порядок показа", default=100)
    is_active = models.BooleanField("включена", default=True)
    # Внутри категории клиент может не знать, что именно ему нужно
    # («подберите на месте»): тогда он записывается без услуги, а мастер
    # перезванивает и выбирает её вместе с ним. Для мойки такой выбор
    # бессмысленен, поэтому это галочка категории, а не правило на всю сеть.
    allow_on_site = models.BooleanField(
        "можно подобрать на месте",
        default=True,
        help_text="Клиент сможет записаться, не выбрав услугу: мастер перезвонит и подберёт её.",
    )
    # Дневник водителя берёт замены масла из выполненных записей. Пока
    # услуга была одна, годилась любая запись; с мойкой и шиномонтажом
    # нужен вид — иначе мойка сбрасывала бы напоминание о масле.
    journal_kind = models.CharField(
        "вид для дневника",
        max_length=16,
        choices=ServiceJournalKind.choices,
        default=ServiceJournalKind.OTHER,
        help_text="Чем выполненная запись станет в дневнике клиента. "
        "Напоминание о масле двигают только категории вида «Замена масла».",
    )

    class Meta:
        verbose_name = "категория услуг"
        verbose_name_plural = "категории услуг"
        ordering = ["service_point", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["service_point", "name"], name="uniq_category_per_point"
            )
        ]
        indexes = [models.Index(fields=["service_point", "is_active", "sort_order"])]

    def __str__(self) -> str:
        return f"{self.name} @ {self.service_point.name}"


class Service(BaseModel):
    """Услуга внутри категории: что делаем и сколько это стоит.

    Цена — одной суммой (решение заказчика): мастер называет клиенту
    итог, а не слагаемые. `material_price` — та часть суммы, которая
    ушла на расходник; по ней считается разбивка «материал и работа» в
    метриках и база баллов в режиме `REFERRAL_BASE=work`. Ноль —
    услуга без материала, и тогда вся цена считается работой.

    Количество учитывается только у услуг с галочкой «ограничено»:
    канистры кончаются, мойка — нет. Остаток лежит прямо здесь, а не
    отдельной таблицей по точкам, потому что услуга и так принадлежит
    одной точке — через свою категорию.
    """

    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.CASCADE,
        related_name="services",
        verbose_name="категория",
    )
    name = models.CharField("название", max_length=160)
    description = models.TextField("описание", blank=True)
    price = models.DecimalField(
        "цена, ₽", max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    material_price = models.DecimalField(
        "из них материал, ₽",
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Часть цены, которая ушла на расходник. Ноль — услуга без материала.",
    )
    is_limited = models.BooleanField(
        "количество ограничено",
        default=False,
        help_text="Отмечено — ведём остаток: услуга пропадает у клиента, когда он кончился.",
    )
    quantity = models.PositiveIntegerField(
        "остаток",
        default=0,
        help_text="Сколько есть сейчас. Учитывается только при «количество ограничено».",
    )
    is_active = models.BooleanField("включена в работу", default=True)
    sort_order = models.PositiveSmallIntegerField("порядок показа", default=100)
    # Из какой позиции масла выросла услуга. Нужна двум местам: старому
    # API масел, которое остаётся работать, пока обновляются приложения,
    # и панели — показать вязкость и объём канистры. Пусто — услугу
    # сразу завели услугой.
    oil = models.ForeignKey(
        Oil,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="services",
        verbose_name="масло",
    )

    class Meta:
        verbose_name = "услуга"
        verbose_name_plural = "услуги"
        ordering = ["category", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "name"], name="uniq_service_per_category"
            ),
            # Материал — часть цены, а не добавка к ней: иначе «работа»
            # уходила бы в минус и утягивала за собой метрики и баллы.
            models.CheckConstraint(
                condition=models.Q(material_price__lte=models.F("price")),
                name="service_material_not_above_price",
            ),
        ]
        indexes = [models.Index(fields=["category", "is_active", "sort_order"])]

    def __str__(self) -> str:
        return self.name

    @property
    def service_point_id(self):
        return self.category.service_point_id

    @property
    def work_price(self):
        """Работа — остаток цены после материала: от неё считаются баллы
        в режиме `REFERRAL_BASE=work` и доля работ в метриках."""
        return self.price - self.material_price

    @property
    def total_price(self):
        """Итог за услугу. Имя общее с `Oil`, чтобы сериализаторы и
        шаблоны не разбирались, что перед ними."""
        return self.price


def _with_index(kwargs: dict) -> dict:
    """Дописать `search_index` в `update_fields`, если он там задан.

    `update_or_create` в Django 5 сохраняет объект с
    `update_fields=set(defaults)` — то есть только теми полями, что ему
    передали. Вычисленный в `save()` индекс в этот список не попадает и
    молча не доезжает до базы: объект сохранён, поиск ищет по старому
    значению, ошибок нет ни одной.
    """
    fields = kwargs.get("update_fields")
    if fields is not None:
        kwargs["update_fields"] = {*fields, "search_index", "updated_at"}
    return kwargs


def _terms(raw: str) -> list[str]:
    """Синонимы из поля в отдельные слова.

    Разделять обязательно: `search_index` выбрасывает запятые, и «мерс,
    мерседес» склеилось бы в «mersmersedes» — одно длинное слово, по
    которому находится всякий мусор.
    """
    return [part.strip() for part in raw.split(",") if part.strip()]


class CarMake(BaseModel):
    """Марка автомобиля для подсказок при заполнении профиля.

    Справочник — именно подсказка, а не ограничение: в профиле остаётся
    свободная строка. Редкую или новую машину клиент впишет сам, и
    регистрация не упрётся в неполноту нашего списка.
    """

    name = models.CharField("марка", max_length=64, unique=True)
    # Всё, по чему марку могут искать: русское написание, разговорные
    # сокращения, прежние имена. Заполняется человеком, в поиск попадает
    # через search_index.
    search_terms = models.CharField(
        "синонимы для поиска",
        max_length=255,
        blank=True,
        help_text="Через запятую: мерс, мерседес, merc",
    )
    # Предпосчитанная форма для сравнения. Хранится, а не считается на
    # лету: иначе поиск превратился бы в перебор таблицы в Python.
    search_index = models.CharField(
        "поисковая форма", max_length=512, blank=True, editable=False, db_index=True
    )
    # Порядок в списке «просто открыл выбор марки». По алфавиту он
    # начинался бы с Acura и Alfa Romeo, а не с того, что реально
    # заезжает на замену.
    sort_order = models.PositiveSmallIntegerField("порядок в списке", default=100)
    is_active = models.BooleanField("показывать", default=True)

    class Meta:
        verbose_name = "марка автомобиля"
        verbose_name_plural = "марки автомобилей"
        ordering = ("sort_order", "name")
        indexes = [models.Index(fields=["is_active", "sort_order", "name"])]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.search_index = build_search_index(self.name, *_terms(self.search_terms))
        super().save(*args, **_with_index(kwargs))
        # Синонимы марки входят и в индекс её моделей: «кия рио» должно
        # находиться так же, как «kia rio». Пересобираем их здесь, иначе
        # правка синонимов в админке молча оставила бы модели со старым
        # индексом. Марок десятки, правят их редко — цена копеечная.
        for model in self.models.all():
            model.save(update_fields=["search_index", "updated_at"])


class CarModel(BaseModel):
    """Модель в пределах марки. Тоже только подсказка."""

    make = models.ForeignKey(
        CarMake, on_delete=models.CASCADE, related_name="models", verbose_name="марка"
    )
    name = models.CharField("модель", max_length=64)
    search_terms = models.CharField(
        "синонимы для поиска", max_length=255, blank=True
    )
    search_index = models.CharField(
        "поисковая форма", max_length=512, blank=True, editable=False, db_index=True
    )
    is_active = models.BooleanField("показывать", default=True)

    class Meta:
        verbose_name = "модель автомобиля"
        verbose_name_plural = "модели автомобилей"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["make", "name"], name="uniq_model_per_make"
            )
        ]
        indexes = [models.Index(fields=["make", "is_active", "name"])]

    def __str__(self) -> str:
        return f"{self.make.name} {self.name}"

    def save(self, *args, **kwargs):
        # В индекс модели входит и марка: человек ищет «киа рио» одной
        # строкой, не разделяя её на два поля.
        self.search_index = build_search_index(
            self.make.name,
            *_terms(self.make.search_terms),
            self.name,
            *_terms(self.search_terms),
        )
        super().save(*args, **_with_index(kwargs))
