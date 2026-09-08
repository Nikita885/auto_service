from django.db import models


class UserRole(models.TextChoices):
    CLIENT = "client", "Клиент"
    MASTER = "master", "Мастер"
    ADMIN = "admin", "Администратор"
