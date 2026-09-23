"""Бизнес-логика аккаунтов: выдача и проверка SMS-кода, вход.

Вьюхи здесь ничего не решают — они только валидируют вход и зовут функции
отсюда. Это же используется тестами и management-командами.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.constants import UserRole
from apps.accounts.models import OtpCode, User
from apps.common.exceptions import (
    ConflictError,
    PermissionError_,
    RateLimitError,
    ValidationError,
)
from apps.common.phone import mask_phone, normalize_phone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OtpChallenge:
    phone: str
    expires_at: object
    resend_after_seconds: int
    debug_code: str | None = None


@dataclass(frozen=True)
class AuthResult:
    user: User
    access: str
    refresh: str
    is_new_user: bool


def _generate_code() -> str:
    length = settings.OTP["CODE_LENGTH"]
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def request_otp(raw_phone: str, *, ip: str | None = None) -> OtpChallenge:
    """Выдать новый код на телефон.

    Защита стоит на трёх уровнях: пауза между отправками, часовой лимит на
    номер и throttling на уровне DRF по IP. SMS стоят денег, а номер
    чужого человека можно завалить спамом.
    """

    phone = normalize_phone(raw_phone)
    now = timezone.now()
    conf = settings.OTP

    last = OtpCode.objects.for_phone(phone).order_by("-created_at").first()
    if last:
        cooldown_ends = last.created_at + timedelta(
            seconds=conf["RESEND_COOLDOWN_SECONDS"]
        )
        if cooldown_ends > now:
            raise RateLimitError(
                "Код уже отправлен, подождите перед повторной отправкой",
                code="otp_cooldown",
                details={"retry_after": int((cooldown_ends - now).total_seconds())},
            )

    sent_last_hour = OtpCode.objects.for_phone(phone).filter(
        created_at__gte=now - timedelta(hours=1)
    ).count()
    if sent_last_hour >= conf["MAX_PER_PHONE_PER_HOUR"]:
        raise RateLimitError(
            "Слишком много запросов кода на этот номер. Попробуйте через час.",
            code="otp_hourly_limit",
        )

    code = _generate_code()
    expires_at = now + timedelta(seconds=conf["TTL_SECONDS"])

    with transaction.atomic():
        # Предыдущие коды гасим: рабочим остаётся только последний.
        OtpCode.objects.for_phone(phone).active().update(expires_at=now)
        OtpCode.objects.create(
            phone=phone,
            code_hash=make_password(code),
            expires_at=expires_at,
            request_ip=ip,
        )

    from apps.notifications.services import send_otp_sms

    send_otp_sms(phone=phone, code=code)
    # Телефон в логах маскируем: это персональные данные, а лог живёт
    # дольше и доступен шире, чем база.
    logger.info("OTP выдан для %s", mask_phone(phone))

    return OtpChallenge(
        phone=phone,
        expires_at=expires_at,
        resend_after_seconds=conf["RESEND_COOLDOWN_SECONDS"],
        debug_code=code if _may_expose_code(phone, conf) else None,
    )


def _may_expose_code(phone: str, conf: dict) -> bool:
    """Можно ли вернуть код прямо в ответе API.

    Два случая. В разработке — всем, чтобы не поднимать SMS-шлюз. В проде —
    только номерам из `OTP_DEBUG_PHONES`: это временная заглушка на время,
    пока у шлюза не согласован буквенный отправитель и SMS не уходят вовсе.

    Использование заглушки пишется в лог предупреждением: она должна
    попадаться на глаза, а не тихо жить в конфиге месяцами.
    """
    if conf["DEBUG_EXPOSE_CODE"]:
        return True
    if phone in _debug_phones(conf):
        logger.warning(
            "Код входа для %s отдан в ответе API: номер в OTP_DEBUG_PHONES. "
            "Это временная заглушка, уберите её после запуска SMS",
            mask_phone(phone),
        )
        return True
    return False


def _debug_phones(conf: dict) -> set[str]:
    """Белый список, приведённый к E.164.

    В `.env` номер напишут как придётся — «8 915…», «+7 915…». Сравнивать
    с ним ненормализованную строку значит получить заглушку, которая молча
    не работает, и полдня искать почему.
    """
    normalized = set()
    for raw in conf["DEBUG_PHONES"]:
        try:
            normalized.add(normalize_phone(raw))
        except ValidationError:
            logger.warning("OTP_DEBUG_PHONES: не разобрал номер %r, пропускаю", raw)
    return normalized


def verify_otp(raw_phone: str, code: str) -> AuthResult:
    """Проверить код и войти. Нет аккаунта — создаём его здесь же."""

    phone = normalize_phone(raw_phone)
    conf = settings.OTP

    otp = OtpCode.objects.for_phone(phone).active().order_by("-created_at").first()
    if otp is None:
        raise ValidationError(
            "Код не найден или истёк. Запросите новый.", code="otp_not_found"
        )

    # Попытку занимаем до сверки кода, одним условным UPDATE. Прочитать
    # счётчик и потом увеличить его нельзя: параллельные запросы видят один
    # и тот же `attempts=0`, и лимит в пять попыток превращается в «сколько
    # запросов успели отправить разом» — при четырёх цифрах это перебор.
    # Условие в WHERE Postgres перепроверяет после чужого UPDATE той же
    # строки, поэтому больше MAX_VERIFY_ATTEMPTS попыток не пройдёт никогда.
    # Вне транзакции успеха — счётчик обязан пережить отказ.
    reserved = OtpCode.objects.filter(
        pk=otp.pk, attempts__lt=conf["MAX_VERIFY_ATTEMPTS"]
    ).update(attempts=F("attempts") + 1)
    if not reserved:
        OtpCode.objects.filter(pk=otp.pk).update(expires_at=timezone.now())
        raise RateLimitError(
            "Слишком много неверных попыток. Запросите новый код.",
            code="otp_attempts_exceeded",
        )

    if not check_password(code, otp.code_hash):
        used = OtpCode.objects.filter(pk=otp.pk).values_list("attempts", flat=True).get()
        attempts_left = max(conf["MAX_VERIFY_ATTEMPTS"] - used, 0)
        raise ValidationError(
            "Неверный код",
            code="otp_invalid",
            details={"attempts_left": attempts_left},
        )

    with transaction.atomic():
        updated = OtpCode.objects.filter(pk=otp.pk, used_at__isnull=True).update(
            used_at=timezone.now()
        )
        if not updated:
            # Кто-то уже погасил этот код параллельным запросом.
            raise ConflictError("Код уже использован", code="otp_already_used")

        user, is_new = User.objects.get_or_create(
            phone=phone,
            defaults={"role": UserRole.CLIENT},
        )
        if is_new:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            _ensure_referral_node(user)

    if not user.is_active:
        raise PermissionError_("Аккаунт заблокирован", code="user_blocked")

    tokens = issue_tokens(user)
    logger.info("Вход %s (новый: %s)", mask_phone(phone), is_new)
    return AuthResult(user=user, is_new_user=is_new, **tokens)


def _ensure_referral_node(user: User) -> None:
    """Завести клиенту место в матрице сразу при регистрации.

    Импорт локальный: `apps.accounts` не должен зависеть от рефералки на
    уровне модуля — так же сделано в `booking.services.booking.complete()`.

    Без этого вызова программа не работала вовсе: узел появлялся только у
    того, кто ввёл чужой код, а начисления ищут узел заплатившего и на
    его отсутствии молча выходят. То есть первый же клиент без кода
    обрывал цепочку для всех, кто над ним.
    """
    if user.role != UserRole.CLIENT:
        return

    from apps.referral.services import tree as referral_tree

    referral_tree.ensure_node(user)


def issue_tokens(user: User) -> dict[str, str]:
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    refresh["phone"] = user.phone
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


def update_profile(user: User, **fields) -> User:
    """Обновление профиля. Телефон и роль сменить через профиль нельзя."""

    allowed = {"full_name", "car_model", "car_plate"}
    dirty = []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        setattr(user, key, value)
        dirty.append(key)

    if dirty:
        user.save(update_fields=dirty)
    return user
