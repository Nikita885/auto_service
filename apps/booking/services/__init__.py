"""Сервисный слой записи.

Вьюхи и Celery-задачи работают только через эти модули; ORM-запросы на
запись за пределами `services/` — повод развернуть ревью.
"""

from apps.booking.services import booking, draft, slots, stock, walk_in  # noqa: F401

__all__ = ["booking", "draft", "slots", "stock", "walk_in"]
