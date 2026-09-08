import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Даты создания/изменения. Наследуют почти все модели проекта."""

    created_at = models.DateTimeField("создано", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("изменено", auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """UUID вместо автоинкремента для всего, что уходит наружу в API.

    Публичные id не должны раскрывать количество клиентов и записей
    и не должны быть перебираемыми.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    class Meta:
        abstract = True
