from config.settings.base import *  # noqa: F401,F403
from config.settings.base import env

DEBUG = False

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
