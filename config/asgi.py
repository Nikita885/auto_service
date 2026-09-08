import os

from django.conf import settings
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# HTTP-приложение должно быть создано до импорта consumers,
# иначе Django-модели будут импортированы до app registry ready.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402

from apps.common.ws_auth import JWTAuthMiddleware  # noqa: E402
from config.routing import websocket_urlpatterns  # noqa: E402

# Daphne — не runserver: сам по себе он статику не отдаёт, а `staticfiles`
# подменяет обработчик только в команде runserver. В разработке оборачиваем
# HTTP-приложение вручную, иначе CSS и JS страниц отдаются как 404.
# В проде статику раздаёт nginx перед daphne — там обёртка не нужна.
http_app = ASGIStaticFilesHandler(django_asgi_app) if settings.DEBUG else django_asgi_app

application = ProtocolTypeRouter(
    {
        "http": http_app,
        "websocket": JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)
