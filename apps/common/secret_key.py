"""Проверка SECRET_KEY. Без зависимостей — модуль читают настройки прода.

Вынесено отдельно, чтобы одну и ту же проверку выполняли и `settings/prod.py`
при старте, и `manage.py security_audit`. Два разных представления о том,
какой ключ считается негодным, — это ровно тот случай, когда аудит зелёный,
а дыра на месте.

`SECRET_KEY` подписывает не только cookie сессии, но и JWT
(`SIMPLE_JWT["SIGNING_KEY"] = SECRET_KEY`). Публично известное значение
здесь — это возможность выписать себе токен любого пользователя, включая
администратора, ничего не взламывая.
"""

from __future__ import annotations

# Значения, которые лежат в репозитории и потому известны всем. Каждое из них
# когда-нибудь доедет до прода: `.env` копируют с `.env.example` и правят не
# целиком.
PLACEHOLDER_SECRET_KEYS = frozenset(
    {
        "insecure-dev-key",
        "change-me-in-production-please-use-50-random-chars",
    }
)

# 50 символов — то, что генерирует рекомендованная в README команда
# `secrets.token_urlsafe(50)`. Короче стоит замечать, но не падать из-за
# этого: ключ на 40 случайных символов не подбирается.
MIN_SECRET_KEY_LENGTH = 50


def is_placeholder_secret_key(value: str) -> bool:
    """Ключ из репозитория — то есть публично известный."""
    return value in PLACEHOLDER_SECRET_KEYS


def secret_key_problem(value: str) -> str | None:
    """Описание проблемы или None, если с ключом всё в порядке.

    Текст пишется так, чтобы читаться после названия настройки: его
    подставляет `security_audit` в строку отчёта.
    """
    if not value:
        return "пуст"
    if is_placeholder_secret_key(value):
        return (
            "значение из репозитория, оно известно всем. Этим ключом "
            "подписываются JWT: подделать токен администратора может любой"
        )
    if len(value) < MIN_SECRET_KEY_LENGTH:
        return f"короче {MIN_SECRET_KEY_LENGTH} символов (сейчас {len(value)})"
    return None
