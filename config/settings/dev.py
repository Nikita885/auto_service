from config.settings.base import *  # noqa: F401,F403
from config.settings.base import REST_FRAMEWORK

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True

# В деве удобно щёлкать API прямо из браузера.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = (
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
)
