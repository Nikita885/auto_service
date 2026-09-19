"""Реферальная программа: матрица участников и журнал баллов.

Схема — принудительная матрица: под каждым участником ровно два места
(`REFERRAL["WIDTH"]`), и начисления идут на три линии вверх от того, кто
заплатил (`REFERRAL["LEVEL_PERCENTS"]` — 5 %, 4 %, 3 %).

Почему матрица, а не классическая бинарка с выплатой за меньшее плечо:
замену масла делают раз в 6–12 месяцев, и «слабое» плечо наполняется
месяцами. Схема, которая полгода не платит ничего, перестаёт работать
раньше, чем участник увидит первый балл. Матрица платит с первого же визита
приглашённого, а переполнение (спиловер) капает и тем, кто сам никого не
привёл, — при годовом цикле это единственное, что удерживает людей.
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
