from django.core.exceptions import ImproperlyConfigured

from apps.common.secret_key import is_placeholder_secret_key
from config.settings.base import *  # noqa: F401,F403
from config.settings.base import OTP, REST_FRAMEWORK, SECRET_KEY, env

DEBUG = False

# Ключ из репозитория подписывает JWT — с ним любой выписывает себе токен
# администратора. Это не «замечание в аудите», а открытая система, поэтому
# прод с таким ключом не стартует вовсе. Остальные слабости ключа (длина)
# разбирает `manage.py security_audit`: падать из-за них — значит уронить
# работающий сайт ради предупреждения.
if is_placeholder_secret_key(SECRET_KEY):
    raise ImproperlyConfigured(
        "SECRET_KEY взят из репозитория и известен всем. Сгенерируйте свой: "
        "python3 -c \"import secrets; print(secrets.token_urlsafe(50))\" "
        "и пропишите в .env. Внимание: смена ключа разлогинивает всех — "
        "старые JWT перестают проверяться."
    )

# Код входа в ответе API — это вход в любой аккаунт по одному лишь номеру
# телефона. В проде переключателя для этого нет вовсе: настройка читается,
# но результат всегда False. Опечатка в .env не должна открывать дверь.
OTP["DEBUG_EXPOSE_CODE"] = False

# За nginx реальный адрес клиента — последний элемент X-Forwarded-For
# (nginx дописывает его через $proxy_add_x_forwarded_for). Значение по
# умолчанию именно здесь, а не в .env: забытая переменная не должна
# превращать лимит по IP в лимит на весь сайт — REMOTE_ADDR за прокси у
# всех один и тот же, 127.0.0.1.
REST_FRAMEWORK["NUM_PROXIES"] = env.int("NUM_PROXIES", default=1)

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Статика с хешем в имени: `landing.a1b2c3d4.css` вместо `landing.css`.
# nginx отдаёт /static/ с длинным сроком жизни, и без хеша выкатка нового
# оформления не доезжает до тех, кто уже был на сайте: HTML свежий, CSS из
# кеша браузера. Сменить адрес файла — единственный способ это пробить.
# Подробности, почему хранилище «прощающее», — в apps/common/staticfiles.py.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "apps.common.staticfiles.ForgivingManifestStaticFilesStorage"
    },
}

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:  # pragma: no cover
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
