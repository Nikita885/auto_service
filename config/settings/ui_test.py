"""Изолированный HTTP-сервер браузерных тестов. Не использовать на проде."""

from config.settings.test import *  # noqa: F403
from config.settings.test import SMS

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
SMS = {**SMS, "PROVIDER": "console"}
