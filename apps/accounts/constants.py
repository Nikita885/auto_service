from django.db import models


class UserRole(models.TextChoices):
    CLIENT = "client", "Клиент"
    MASTER = "master", "Мастер"
    ADMIN = "admin", "Администратор"


class OtpChannel(models.TextChoices):
    """Как доставлен код входа."""

    #: Звонок, код — последние цифры номера, с которого звонят. По умолчанию.
    CALL = "call", "Звонок"
    #: SMS — когда звонки не помогли (см. OTP_CALLS_BEFORE_SMS).
    SMS = "sms", "SMS"
