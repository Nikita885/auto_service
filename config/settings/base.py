"""Базовые настройки проекта.

Разделение на base/dev/prod/test — чтобы прод-настройки нельзя было случайно
получить в разработке и наоборот. Всё окружение читается через django-environ.
"""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# ---------------------------------------------------------------- core
SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# ---------------------------------------------------------------- apps
DJANGO_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Нужен лендингу: разряды в числах («14 000 машин»).
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    "channels",
    "django_celery_beat",
]

LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.catalog",
    "apps.booking",
    "apps.notifications",
    "apps.master",
    "apps.referral",
    "apps.web",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "apps" / "web" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------- db
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="autoservice"),
        "USER": env("POSTGRES_USER", default="autoservice"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="autoservice"),
        "HOST": env("POSTGRES_HOST", default="localhost"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
        "CONN_MAX_AGE": 60,
        "ATOMIC_REQUESTS": False,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# ---------------------------------------------------------------- cache
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

# ---------------------------------------------------------------- channels
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env("CHANNELS_REDIS_URL", default="redis://localhost:6379/3")]
        },
    }
}

# ---------------------------------------------------------------- celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "Europe/Moscow"
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BEAT_SCHEDULE = {
    "expire-stale-drafts": {
        "task": "apps.booking.tasks.expire_stale_drafts",
        "schedule": 20.0,
    },
    "send-booking-reminders": {
        "task": "apps.booking.tasks.send_booking_reminders",
        "schedule": 300.0,
    },
    "purge-old-drafts": {
        "task": "apps.booking.tasks.purge_old_drafts",
        "schedule": 86400.0,
    },
    "purge-expired-otp": {
        "task": "apps.accounts.tasks.purge_expired_otp",
        "schedule": 3600.0,
    },
}

# ---------------------------------------------------------------- DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {
        "otp_request": "10/hour",
        "otp_verify": "20/hour",
        "booking_write": "60/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env.int("JWT_ACCESS_LIFETIME_MINUTES", default=60)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=env.int("JWT_REFRESH_LIFETIME_DAYS", default=30)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Автосервис — API замены масла",
    "DESCRIPTION": (
        "Бэкенд записи на замену масла: вход по SMS-коду, пошаговая запись "
        "с черновиком на 5 минут, панель мастера."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True

# Django 4+ сверяет Origin форм с этим списком, а не с ALLOWED_HOSTS. За HTTPS
# без него вход в админку и панели сотрудников отдаёт 403: браузер шлёт Origin,
# схему которого Django считает чужой.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# ---------------------------------------------------------------- i18n
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "UTC"  # в БД всё в UTC, локальное время берём из часового пояса точки
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------- бизнес-правила
# Единая точка правды: любое из этих чисел меняется без правок кода.
BOOKING = {
    # Сколько живёт черновик записи с момента старта (ТЗ: 5 минут).
    "DRAFT_TTL_SECONDS": env.int("BOOKING_DRAFT_TTL_SECONDS", default=300),
    # Минимальный запас до слота: нельзя записаться на «через минуту».
    "MIN_LEAD_MINUTES": env.int("BOOKING_MIN_LEAD_MINUTES", default=30),
    # На сколько дней вперёд открыта запись.
    "HORIZON_DAYS": env.int("BOOKING_HORIZON_DAYS", default=14),
    # За сколько минут до слота клиент ещё может отменить сам.
    "CANCEL_DEADLINE_MINUTES": env.int("BOOKING_CANCEL_DEADLINE_MINUTES", default=60),
    # За сколько минут до слота слать напоминание.
    "REMINDER_LEAD_MINUTES": env.int("BOOKING_REMINDER_LEAD_MINUTES", default=120),
    # Через сколько дней физически удалять мёртвые черновики.
    "DRAFT_PURGE_AFTER_DAYS": env.int("BOOKING_DRAFT_PURGE_AFTER_DAYS", default=7),
}

OTP = {
    "TTL_SECONDS": env.int("OTP_TTL_SECONDS", default=300),
    "RESEND_COOLDOWN_SECONDS": env.int("OTP_RESEND_COOLDOWN_SECONDS", default=60),
    "MAX_VERIFY_ATTEMPTS": env.int("OTP_MAX_VERIFY_ATTEMPTS", default=5),
    "MAX_PER_PHONE_PER_HOUR": env.int("OTP_MAX_PER_PHONE_PER_HOUR", default=5),
    "CODE_LENGTH": 4,
    # В деве возвращаем код прямо в ответе, чтобы не поднимать SMS-шлюз.
    "DEBUG_EXPOSE_CODE": env.bool("OTP_DEBUG_EXPOSE_CODE", default=False),
}

SMS = {
    "PROVIDER": env("SMS_PROVIDER", default="console"),
    "API_KEY": env("SMS_API_KEY", default=""),
    # Имя отправителя согласуется у оператора отдельно. Пока не согласовано,
    # оставьте пустым: шлюз отклонит отправку с чужим именем.
    "SENDER": env("SMS_SENDER", default=""),
    # Какие уведомления реально уходят. Каждое стоит денег, и основной
    # расход — не коды входа, а «запись создана» и «работы выполнены»: их
    # клиент и так видит в приложении. Пустой список = не слать ничего.
    "ENABLED_KINDS": env.list(
        "SMS_ENABLED_KINDS",
        default=[
            "otp",
            "booking_created",
            "booking_reminder",
            "booking_cancelled_by_master",
            "booking_completed",
        ],
    ),
}

# Часовой пояс, в котором сотрудники думают о «сегодня».
# Локальное время конкретной точки всегда берётся из ServicePoint.timezone.
BUSINESS_TIMEZONE = env("BUSINESS_TIMEZONE", default="Europe/Moscow")

DEFAULT_PHONE_REGION = "RU"

# ------------------------------------------------------- реферальная программа
# Схема — принудительная матрица: под участником два места, начисления идут
# на три линии вверх от того, кто заплатил. Классическая бинарка с выплатой
# за меньшее плечо тут не работает: замену делают раз в 6–12 месяцев, и
# слабое плечо наполняется месяцами.
REFERRAL = {
    "ENABLED": env.bool("REFERRAL_ENABLED", default=True),
    # Проценты по линиям вниз от получателя: первая, вторая, третья. Длина
    # списка задаёт и глубину — четвёртое число включит четвёртую линию.
    "LEVEL_PERCENTS": [
        Decimal(str(value))
        for value in env.list("REFERRAL_LEVEL_PERCENTS", default=["5", "4", "3"])
    ],
    # С какой части чека считаем: "total" — масло плюс работа, "work" —
    # только работа. От работы нагрузка ровнее: масло перепродаётся с почти
    # фиксированной наценкой, и дорогая канистра увеличивает чек, не
    # увеличивая заработок.
    "BASE": env("REFERRAL_BASE", default="total"),
    # Сколько мест под участником. 2 — бинарная матрица.
    "WIDTH": env.int("REFERRAL_WIDTH", default=2),
    # Потолок оплаты баллами, % от чека: баллы — скидка, а не вторая касса.
    "MAX_DISCOUNT_PERCENT": env.int("REFERRAL_MAX_DISCOUNT_PERCENT", default=50),
}

# ---------------------------------------------------------------- лендинг
# Контакты и ссылки на магазины приложений. Лежат в .env, а не в шаблоне:
# телефон и ссылки меняет не программист, и правка не должна требовать
# ни редактирования кода, ни пересборки образа.
COMPANY = {
    "NAME": env("COMPANY_NAME", default="Мой Сервис"),
    "TAGLINE": env("COMPANY_TAGLINE", default="Замена масла по записи"),
    "PHONE": env("COMPANY_PHONE", default="+7 (499) 123-45-67"),
    "EMAIL": env("COMPANY_EMAIL", default="hello@example.com"),
    "WORKING_HOURS": env("COMPANY_WORKING_HOURS", default="Ежедневно 09:00–21:00"),
    # Пока приложения не опубликованы, ссылки пустые — кнопки в этом случае
    # показываются неактивными с пометкой «скоро», а не ведут в никуда.
    "APP_STORE_URL": env("COMPANY_APP_STORE_URL", default=""),
    "GOOGLE_PLAY_URL": env("COMPANY_GOOGLE_PLAY_URL", default=""),
    "YEARS_ON_MARKET": env.int("COMPANY_YEARS_ON_MARKET", default=8),
    "CARS_SERVED": env.int("COMPANY_CARS_SERVED", default=14000),
    # Показывать ли цены на сайте. Заказчик может не хотеть раскрывать
    # стоимость публично: тогда на лендинге остаётся ассортимент масел без
    # сумм, а цену клиент узнаёт по телефону или в приложении.
    "SHOW_PRICES": env.bool("COMPANY_SHOW_PRICES", default=False),
}

# ---------------------------------------------------------------- logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name}:{lineno} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
        "apps": {
            "level": "DEBUG" if DEBUG else "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
    },
}
