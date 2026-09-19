from django.db import models


class MatrixPosition(models.TextChoices):
    """Место под родителем в матрице. Ширина матрицы = число вариантов."""

    LEFT = "left", "левое"
    RIGHT = "right", "правое"


class PointsKind(models.TextChoices):
    """Что за движение баллов. Журнал — единственный источник правды."""

    ACCRUAL = "accrual", "начисление"
    SPEND = "spend", "списание"
    ADJUSTMENT = "adjustment", "корректировка"
