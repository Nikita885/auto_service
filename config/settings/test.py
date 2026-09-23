from config.settings.base import *  # noqa: F401,F403
from config.settings.base import OTP, REST_FRAMEWORK

DEBUG = False

# Тесты не должны ходить в брокер.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Быстрый хешер: иначе PBKDF2 съедает всё время прогона.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Тестируем бизнес-лимиты (кулдаун, попытки), а не DRF-throttling по IP.
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "otp_request": "100000/hour",
    "otp_verify": "100000/hour",
    "booking_write": "100000/min",
    # Словарь заменяется целиком: забытая область роняет свою вьюху с
    # ImproperlyConfigured — так уже падала проверка кода приглашения.
    "referral_check": "100000/hour",
}

OTP["DEBUG_EXPOSE_CODE"] = True
