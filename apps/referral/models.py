"""Реферальная программа: бинарное дерево участников и журнал баллов.

Под каждым участником два места — левое и правое плечо. Когда кто-то в
ветке оплатил замену, его чек превращается в баллы для трёх вышестоящих:
первая линия получает 5 %, вторая 4 %, третья 3 % (`LEVEL_PERCENTS`).
Баллы ложатся не на баланс, а в то плечо участника, где стоит покупатель
(`LegCredit`).

Раз в сутки, в 00:00 по Челябинску (`PAYOUT_TIMEZONE`), плечи сводятся
(`BinarySettlement`): если одно пустое — выплаты нет и всё переносится;
если равны — выплачиваются оба; иначе выплачивается меньшее, а излишек
сильного переносится на следующие сутки. Правила — от заказчика, расчёт
на полном дереве совпадает с его таблицей: 600 + 960 + 1440 = 3000 баллов
с участника при чеке 6000 ₽.

Размещение новичков — обходом в ширину от пригласившего (`services/tree`),
со спиловером: оба места у спонсора заняты — человек встаёт ниже в его ветке.
"""

from django.conf import settings
from django.db import models

from apps.common.codes import generate_code
from apps.common.models import BaseModel
from apps.referral.constants import MatrixPosition, PointsKind


def generate_referral_code() -> str:
    """Код приглашения. Отдельная обёртка — на неё ссылается миграция."""
    return generate_code(6)


class ReferralNode(BaseModel):
    """Место клиента в матрице.

    `sponsor` и `parent` — разные вещи, и это важно. `sponsor` — кто реально
    пригласил, по чьему коду человек пришёл. `parent` — под кем он оказался
    в матрице. При спиловере оба места у спонсора заняты, и новичок падает
    ниже, к кому-то из его ветки: начисления пойдут по `parent`, а
    «привёл такого-то» считается по `sponsor`.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_node",
        verbose_name="клиент",
    )
    code = models.CharField(
        "код приглашения",
        max_length=8,
        unique=True,
        default=generate_referral_code,
    )

    sponsor = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invited",
        verbose_name="пригласил",
    )
    # PROTECT, а не CASCADE: удаление узла с детьми разорвало бы матрицу, и
    # вся ветка под ним осталась бы без вышестоящих. Дерево — финансовая
    # история, дырявить его нельзя.
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name="над ним в матрице",
    )
    position = models.CharField(
        "место под родителем",
        max_length=5,
        choices=MatrixPosition.choices,
        blank=True,
    )
    # Глубина от корня. Хранится, а не считается на лету: иначе выборка
    # «покажи дерево участника» упиралась бы в рекурсивный запрос.
    depth = models.PositiveIntegerField("уровень в матрице", default=0, db_index=True)

    balance = models.DecimalField("баллы", max_digits=10, decimal_places=2, default=0)
    # Невыплаченный остаток плеч после последнего сведения. Хранится, а не
    # считается суммой по истории: сведение идёт каждую ночь по всем, и
    # пересчитывать ради него весь журнал с начала времён незачем.
    carry_left = models.DecimalField(
        "перенос левого плеча", max_digits=12, decimal_places=2, default=0
    )
    carry_right = models.DecimalField(
        "перенос правого плеча", max_digits=12, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = "участник программы"
        verbose_name_plural = "участники программы"
        ordering = ("depth", "created_at")
        constraints = [
            # Одно место под родителем занимает ровно один человек. Проверка
            # на уровне БД, а не в коде: два клиента могут регистрироваться
            # одновременно, и выбор свободного места — классическая гонка.
            models.UniqueConstraint(
                fields=["parent", "position"],
                condition=models.Q(parent__isnull=False),
                name="uniq_matrix_slot",
            ),
        ]
        indexes = [models.Index(fields=["parent", "position"])]

    def __str__(self) -> str:
        return f"{self.code} ({self.user_id})"


class PointsEntry(BaseModel):
    """Движение баллов. Баланс узла — производная от этого журнала.

    Денормализованный `ReferralNode.balance` обновляется в той же
    транзакции: читать баланс суммой по журналу на каждый запрос дорого, а
    расходиться им нельзя.
    """

    node = models.ForeignKey(
        ReferralNode,
        on_delete=models.CASCADE,
        related_name="entries",
        verbose_name="кому",
    )
    amount = models.DecimalField("баллы", max_digits=10, decimal_places=2)
    kind = models.CharField("тип", max_length=12, choices=PointsKind.choices)

    booking = models.ForeignKey(
        "booking.Booking",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="points_entries",
        verbose_name="запись",
    )
    source_node = models.ForeignKey(
        ReferralNode,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_entries",
        verbose_name="с чьего чека",
    )
    level = models.PositiveSmallIntegerField("линия", null=True, blank=True)
    # Снимок ставки на момент начисления: проценты меняются в .env, а
    # история не должна переписываться задним числом.
    percent = models.DecimalField(
        "ставка, %", max_digits=5, decimal_places=2, null=True, blank=True
    )
    base_amount = models.DecimalField(
        "база начисления", max_digits=10, decimal_places=2, null=True, blank=True
    )
    comment = models.CharField("комментарий", max_length=255, blank=True)

    class Meta:
        verbose_name = "движение баллов"
        verbose_name_plural = "движения баллов"
        ordering = ("-created_at",)
        constraints = [
            # Одна запись даёт участнику ровно одно начисление. Защита от
            # повторного проведения: `complete()` вызывают люди, и нажать
            # дважды проще, чем кажется.
            models.UniqueConstraint(
                fields=["booking", "node"],
                condition=models.Q(kind=PointsKind.ACCRUAL),
                name="uniq_accrual_per_booking_node",
            ),
        ]
        indexes = [
            models.Index(fields=["node", "-created_at"]),
            models.Index(fields=["kind", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.amount} → {self.node_id}"


class BinarySettlement(BaseModel):
    """Сведение плеч участника за одни сутки — вся арифметика выплаты.

    Хранится целиком, а не одной суммой: «почему мне заплатили 300, а не
    600» — первый вопрос клиента, и ответ должен лежать в базе, а не
    восстанавливаться по журналу.
    """

    node = models.ForeignKey(
        ReferralNode,
        on_delete=models.CASCADE,
        related_name="settlements",
        verbose_name="участник",
    )
    day = models.DateField("сутки (по времени выплат)")
    left_before = models.DecimalField("перенос слева", max_digits=12, decimal_places=2)
    right_before = models.DecimalField("перенос справа", max_digits=12, decimal_places=2)
    left_added = models.DecimalField("пришло слева", max_digits=12, decimal_places=2)
    right_added = models.DecimalField("пришло справа", max_digits=12, decimal_places=2)
    paid = models.DecimalField("выплачено", max_digits=12, decimal_places=2)
    left_after = models.DecimalField("осталось слева", max_digits=12, decimal_places=2)
    right_after = models.DecimalField("осталось справа", max_digits=12, decimal_places=2)
    entry = models.OneToOneField(
        PointsEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="settlement",
        verbose_name="строка журнала",
    )

    class Meta:
        verbose_name = "сведение плеч"
        verbose_name_plural = "сведения плеч"
        ordering = ("-day",)
        constraints = [
            # Одни сутки сводятся один раз: задача идёт по расписанию и
            # может быть запущена повторно — выплата дважды недопустима.
            models.UniqueConstraint(fields=["node", "day"], name="uniq_settlement_per_day"),
        ]

    def __str__(self) -> str:
        return f"{self.node_id} {self.day}: {self.paid}"


class LegCredit(BaseModel):
    """Баллы, пришедшие в плечо участника с чужой покупки, до сведения.

    Одна строка — одна выполненная запись для одного вышестоящего. После
    ночного сведения строка привязывается к `settlement` и больше не
    участвует в расчёте.
    """

    node = models.ForeignKey(
        ReferralNode,
        on_delete=models.CASCADE,
        related_name="leg_credits",
        verbose_name="кому в плечо",
    )
    side = models.CharField("плечо", max_length=5, choices=MatrixPosition.choices)
    amount = models.DecimalField("баллы", max_digits=10, decimal_places=2)
    booking = models.ForeignKey(
        "booking.Booking",
        on_delete=models.PROTECT,
        related_name="leg_credits",
        verbose_name="запись",
    )
    source_node = models.ForeignKey(
        ReferralNode,
        on_delete=models.CASCADE,
        related_name="generated_credits",
        verbose_name="с чьего чека",
    )
    level = models.PositiveSmallIntegerField("линия")
    # Снимок ставки и базы: проценты меняются в .env, история — нет.
    percent = models.DecimalField("ставка, %", max_digits=5, decimal_places=2)
    base_amount = models.DecimalField("база", max_digits=10, decimal_places=2)
    settlement = models.ForeignKey(
        BinarySettlement,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="credits",
        verbose_name="сведено",
    )

    class Meta:
        verbose_name = "баллы в плечо"
        verbose_name_plural = "баллы в плечи"
        ordering = ("-created_at",)
        constraints = [
            # Одна запись даёт вышестоящему ровно одно поступление: мастер
            # может нажать «Выполнено» дважды, двойных баллов быть не должно.
            models.UniqueConstraint(
                fields=["booking", "node"], name="uniq_credit_per_booking_node"
            ),
        ]
        indexes = [
            models.Index(fields=["settlement", "created_at"]),
            models.Index(fields=["node", "settlement"]),
        ]

    def __str__(self) -> str:
        return f"{self.amount} → {self.node_id} ({self.side})"
