"""Бизнес-логика аккаунтов: выдача и проверка SMS-кода, вход.

Вьюхи здесь ничего не решают — они только валидируют вход и зовут функции
отсюда. Это же используется тестами и management-командами.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.constants import OtpChannel, UserRole
from apps.accounts.models import OtpCode, User
from apps.common.exceptions import (
    ConflictError,
    GoneError,
    PermissionError_,
    RateLimitError,
    UnavailableError,
    ValidationError,
)
from apps.common.phone import mask_phone, normalize_phone

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OtpChallenge:
    phone: str
    expires_at: object
    resend_after_seconds: int
    #: Как ушёл код: call — звонок (код — последние 4 цифры номера), sms.
    channel: str = "call"
    #: Можно ли следующий код попросить в SMS: звонки не помогли.
    sms_available: bool = False
    #: Обратный звонок: номер, на который клиент звонит сам.
    number_to_call: str | None = None
    #: Обратный звонок: секрет для опроса статуса (см. `check_call`).
    session: str | None = None
    debug_code: str | None = None


@dataclass(frozen=True)
class AuthResult:
    user: User
    access: str
    refresh: str
    is_new_user: bool
    #: Что стало с кодом приглашения, пришедшим вместе с входом (см. `apply_invite`).
    invite: dict | None = None


def _generate_code() -> str:
    length = settings.OTP["CODE_LENGTH"]
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def request_otp(
    raw_phone: str, *, ip: str | None = None, channel: str | None = None
) -> OtpChallenge:
    """Выдать новый код на телефон: звонком, а после неудачных звонков — SMS.

    Сначала звонок: код — последние цифры номера, с которого позвонят. Он
    дешевле SMS и не зависит от согласованного буквенного отправителя.
    Каждый повторный запрос кода значит, что предыдущий звонок не помог;
    после `CALLS_BEFORE_SMS` таких звонков клиенту предлагают SMS
    (`sms_available`), и он может попросить его явно (`channel="sms"`).
    Шлюз звонков отказал — в том же запросе уходит SMS: войти человек
    должен, даже когда звонки не работают.

    Защита стоит на трёх уровнях: пауза между отправками, часовой лимит на
    номер (звонки и SMS вместе) и throttling на уровне DRF по IP. Каждый
    код стоит денег, а номер чужого человека можно завалить звонками.
    """

    phone = normalize_phone(raw_phone)
    _refuse_staff(phone)
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

    calls = _unsuccessful_calls(phone, now)
    if channel == OtpChannel.SMS and calls < conf["CALLS_BEFORE_SMS"]:
        raise ValidationError(
            "Код в SMS можно получить, если звонок не помог",
            code="otp_sms_not_available",
            details={"calls_left": conf["CALLS_BEFORE_SMS"] - calls},
        )
    channel = channel or OtpChannel.CALL

    # Звонок заказывается синхронно, и между проверкой паузы и записью кода
    # проходит ответ шлюза. Два одновременных запроса прошли бы паузу оба и
    # оплатили бы два звонка — поэтому номер держим коротким замком в кеше
    # (`add` атомарен и в Redis, и в памяти).
    lock = f"otp-request:{phone}"
    if not cache.add(lock, 1, timeout=30):
        raise RateLimitError(
            "Код уже отправляется, подождите",
            code="otp_cooldown",
            details={"retry_after": conf["RESEND_COOLDOWN_SECONDS"]},
        )
    try:
        if conf["MODE"] == "verificahub":
            started = _start_verificahub(phone, channel)
        else:
            started = _start_smsru(phone, ip, channel)
        channel = started["channel"]

        session = secrets.token_urlsafe(24) if channel == OtpChannel.REVERSE_CALL else None
        expires_at = timezone.now() + timedelta(seconds=conf["TTL_SECONDS"])
        with transaction.atomic():
            # Предыдущие коды гасим: рабочим остаётся только последний.
            OtpCode.objects.for_phone(phone).active().update(expires_at=timezone.now())
            OtpCode.objects.create(
                phone=phone,
                # Код, который знает только шлюз, у нас не хранится вовсе:
                # хеш «ничего» не совпадёт ни с одним введённым кодом.
                code_hash=make_password(started["code"]),
                expires_at=expires_at,
                request_ip=ip,
                channel=channel,
                provider_request_id=started["request_id"],
                session_hash=_session_hash(session) if session else "",
            )
            if channel == OtpChannel.SMS and started["request_id"] == "":
                from apps.notifications.services import send_otp_sms

                send_otp_sms(phone=phone, code=started["code"])
    finally:
        cache.delete(lock)

    # Телефон в логах маскируем: это персональные данные, а лог живёт
    # дольше и доступен шире, чем база.
    logger.info("OTP выдан для %s: %s", mask_phone(phone), channel)
    if channel in CALL_CHANNELS:
        calls += 1

    return OtpChallenge(
        phone=phone,
        expires_at=expires_at,
        resend_after_seconds=conf["RESEND_COOLDOWN_SECONDS"],
        channel=channel,
        sms_available=calls >= conf["CALLS_BEFORE_SMS"],
        number_to_call=started.get("number_to_call"),
        session=session,
        debug_code=started["debug_code"] if _may_expose_code(phone, conf) else None,
    )


#: Попытки звонком — после скольких из них без входа предлагается SMS.
CALL_CHANNELS = (OtpChannel.CALL, OtpChannel.REVERSE_CALL)


def _start_smsru(phone: str, ip: str | None, channel: str) -> dict:
    """Режим smsru: звонок с кодом, запасное SMS — через SMS.RU."""
    code = None
    if channel == OtpChannel.CALL:
        code = _place_call(phone, ip)
        if code is None:
            channel = OtpChannel.SMS
    if code is None:
        code = _generate_code()
    return {"channel": channel, "code": code, "request_id": "", "debug_code": code}


def _start_verificahub(phone: str, channel: str) -> dict:
    """Режим verificahub: клиент сам звонит на выданный номер, запасное SMS
    — тоже у VerificaHub. Кода мы не знаем ни в том, ни в другом случае.

    Шлюз не принял обратный звонок — сразу SMS, как и в режиме smsru.
    Не принял и SMS — вход сейчас невозможен, и честнее так и сказать.
    """
    from apps.notifications.providers import SmsDeliveryError, SmsRejectedError
    from apps.notifications.providers import verificahub as vh
    from apps.notifications.services import journal_verification

    gateway = vh.get_verificahub()
    ttl = settings.OTP["TTL_SECONDS"]

    if channel != OtpChannel.SMS:
        try:
            started = gateway.start(phone, vh.REVERSE_CALL, ttl)
        except (SmsDeliveryError, SmsRejectedError) as exc:
            journal_verification(phone=phone, channel="call", error=str(exc))
            logger.warning(
                "Обратный звонок для %s не создан (%s) — отправляем SMS", mask_phone(phone), exc
            )
        else:
            journal_verification(
                phone=phone, channel="call", request_id=started.request_id,
                text=f"Обратный звонок на {started.number_to_call}, {started.cost}",
            )
            return {
                "channel": OtpChannel.REVERSE_CALL, "code": None,
                "request_id": started.request_id, "number_to_call": started.number_to_call,
                "debug_code": None,
            }

    try:
        started = gateway.start(phone, vh.SMS, ttl)
    except (SmsDeliveryError, SmsRejectedError) as exc:
        journal_verification(phone=phone, channel="sms", error=str(exc))
        raise UnavailableError(
            "Не получилось отправить код. Попробуйте через минуту.", code="otp_unavailable"
        ) from exc
    journal_verification(
        phone=phone, channel="sms", request_id=started.request_id,
        text=f"SMS с кодом входа ****, {started.cost}",
    )
    debug = getattr(gateway, "console_code", None)
    return {
        "channel": OtpChannel.SMS, "code": None, "request_id": started.request_id,
        "debug_code": debug(started.request_id) if debug else None,
    }


def _session_hash(session: str) -> str:
    """Сессия — 24 случайных байта, перебирать её незачем: хватает sha256.

    Медленный хеш, как у кодов, тут только мешал бы — приложение опрашивает
    статус раз в две секунды.
    """
    return hashlib.sha256(session.encode()).hexdigest()


def _place_call(phone: str, ip: str | None) -> str | None:
    """Позвонить с кодом. None — шлюз звонков отказал, пора слать SMS."""
    from apps.notifications.providers import SmsDeliveryError, SmsRejectedError
    from apps.notifications.services import call_otp

    try:
        return call_otp(phone=phone, ip=ip)
    except (SmsDeliveryError, SmsRejectedError) as exc:
        logger.warning(
            "Звонок с кодом на %s не заказан (%s) — отправляем SMS", mask_phone(phone), exc
        )
        return None


def _unsuccessful_calls(phone: str, now) -> int:
    """Сколько звонков с кодом было после последнего входа, за последний час.

    Звонок, после которого человек снова просит код, — неудачный: не
    дошёл, сорвался или цифры не разглядели. Входом счёт обнуляется, а
    окно в час совпадает с часовым лимитом — вчерашние звонки не в счёт.
    """
    since = now - timedelta(hours=1)
    last_login = (
        OtpCode.objects.for_phone(phone)
        .filter(used_at__isnull=False, created_at__gte=since)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if last_login is not None:
        since = last_login
    return (
        OtpCode.objects.for_phone(phone)
        .filter(channel__in=CALL_CHANNELS, created_at__gt=since)
        .count()
    )


def _refuse_staff(phone: str) -> None:
    """Сотрудники входят по паролю — вход кодом на их номер закрыт.

    Иначе пароль ничего бы не защищал: код звонком получает любой, у кого
    в руках телефон мастера, а токен даёт доступ к записям всей точки.
    """
    if User.objects.filter(phone=phone).exclude(role=UserRole.CLIENT).exists():
        raise PermissionError_(
            "Сотрудники входят по паролю — на сайте, в панели мастера",
            code="staff_use_password",
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


def verify_otp(raw_phone: str, code: str, *, invite: str = "") -> AuthResult:
    """Проверить код и войти. Нет аккаунта — создаём его здесь же."""

    phone = normalize_phone(raw_phone)
    _refuse_staff(phone)
    conf = settings.OTP

    otp = OtpCode.objects.for_phone(phone).active().order_by("-created_at").first()
    if otp is None:
        raise ValidationError(
            "Код не найден или истёк. Запросите новый.", code="otp_not_found"
        )
    if otp.channel == OtpChannel.REVERSE_CALL:
        raise ValidationError(
            "Код вводить не нужно — позвоните на номер, который показан на экране",
            code="otp_call_required",
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

    if not _code_matches(otp, code):
        used = OtpCode.objects.filter(pk=otp.pk).values_list("attempts", flat=True).get()
        attempts_left = max(conf["MAX_VERIFY_ATTEMPTS"] - used, 0)
        raise ValidationError(
            "Неверный код",
            code="otp_invalid",
            details={"attempts_left": attempts_left},
        )

    return _sign_in(otp, phone, invite)


def _code_matches(otp: OtpCode, code: str) -> bool:
    """Сверить код: свой — по хешу, код шлюза — у самого шлюза."""
    if not otp.provider_request_id:
        return check_password(code, otp.code_hash)

    from apps.notifications.providers import SmsDeliveryError, SmsRejectedError
    from apps.notifications.providers.verificahub import get_verificahub

    try:
        return get_verificahub().check(otp.provider_request_id, code)
    except (SmsDeliveryError, SmsRejectedError) as exc:
        logger.warning("VerificaHub не проверил код для %s: %s", mask_phone(otp.phone), exc)
        raise UnavailableError(
            "Не получилось проверить код. Попробуйте ещё раз.", code="otp_unavailable"
        ) from exc


def check_call(raw_phone: str, session: str, *, invite: str = "") -> AuthResult | None:
    """Обратный звонок: позвонил ли клиент. None — ещё ждём звонка.

    Приложение спрашивает раз в пару секунд, пока клиент звонит. Спросить
    может только тот, кто запрашивал вход: без сессии из ответа на запрос
    кода статус не отдаётся — иначе чужой, знающий номер, вошёл бы в
    аккаунт в тот момент, когда звонит его хозяин.
    """
    from apps.notifications.providers import SmsDeliveryError, SmsRejectedError
    from apps.notifications.providers import verificahub as vh

    phone = normalize_phone(raw_phone)
    _refuse_staff(phone)

    otp = (
        OtpCode.objects.for_phone(phone).active()
        .filter(channel=OtpChannel.REVERSE_CALL)
        .order_by("-created_at").first()
    )
    if otp is None or not secrets.compare_digest(otp.session_hash, _session_hash(session or "")):
        raise ValidationError(
            "Звонок не найден или время вышло. Запросите вход заново.", code="otp_not_found"
        )

    try:
        status = vh.get_verificahub().status(otp.provider_request_id)
    except (SmsDeliveryError, SmsRejectedError) as exc:
        logger.warning("VerificaHub не отдал статус для %s: %s", mask_phone(phone), exc)
        raise UnavailableError(
            "Не получилось проверить звонок. Попробуем ещё раз.", code="otp_unavailable"
        ) from exc

    if status.status == vh.VERIFIED:
        return _sign_in(otp, phone, invite)
    if status.status in vh.PENDING:
        return None

    # Сессия у шлюза закончилась — гасим и у себя, дальше только новый запрос.
    OtpCode.objects.filter(pk=otp.pk).update(expires_at=timezone.now())
    if status.status == "expired":
        raise GoneError("Время на звонок вышло. Запросите вход заново.", code="otp_expired")
    raise ValidationError(
        "Не удалось подтвердить звонок. Запросите вход заново.",
        code="otp_call_failed",
        details={"reason": status.failure_reason or status.status},
    )


def _sign_in(otp: OtpCode, phone: str, invite: str) -> AuthResult:
    """Код подтверждён — погасить его и войти. Нет аккаунта — создать."""
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
    return AuthResult(
        user=user, is_new_user=is_new, invite=apply_invite(user, invite), **tokens
    )


def apply_invite(user: User, code: str) -> dict | None:
    """Привязать клиента по коду из ссылки или QR — без ручного ввода.

    Код приходит вместе со входом: человек открыл ссылку-приглашение или
    отсканировал QR, и дальше ему ничего вводить не нужно. Отказ (код
    неверный, приглашение уже принято, свой код) вход не ломает — клиент
    получает ответ и понятное сообщение, а войти он всё равно должен.
    """
    code = (code or "").strip().upper()
    if not code or user.role != UserRole.CLIENT:
        return None

    from apps.common.exceptions import DomainError
    from apps.referral.services import tree as referral_tree

    try:
        node = referral_tree.attach(user, code)
    except DomainError as exc:
        return {"status": "rejected", "code": exc.code, "message": exc.message}
    return {
        "status": "attached",
        "inviter_name": node.sponsor.user.full_name or "Клиент",
    }


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


def find_client(raw_phone: str) -> User | None:
    """Клиент по номеру в любой записи номера — для подсказки мастеру."""
    return User.objects.filter(phone=normalize_phone(raw_phone)).first()


def get_or_create_client(
    raw_phone: str, *, full_name: str = "", car_model: str = "", car_plate: str = ""
) -> tuple[User, bool]:
    """Клиент, которого записывает мастер: по звонку или у стойки.

    Нет аккаунта — заводим такой же, как при входе по SMS: без пароля и
    сразу с местом в реферальной программе. Потом человек входит в
    приложение по своему номеру и видит свою запись — телефон и есть его
    логин.

    Существующему клиенту профиль не переписываем, а только дополняем
    пустые поля: имя и машину он мог поправить сам, а мастер со слов по
    телефону легко ошибётся. В записи при этом остаётся то, что ввёл
    мастер, — это снимок, как и у записи из приложения.
    """
    phone = normalize_phone(raw_phone)
    profile = {"full_name": full_name, "car_model": car_model, "car_plate": car_plate}
    user, created = User.objects.get_or_create(
        phone=phone, defaults={"role": UserRole.CLIENT, **profile}
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
        _ensure_referral_node(user)
        logger.info("Мастер завёл клиента %s", mask_phone(phone))
        return user, True

    if user.role != UserRole.CLIENT:
        raise ConflictError(
            "Этот номер принадлежит сотруднику", code="phone_is_staff"
        )
    if not user.is_active:
        raise PermissionError_("Аккаунт клиента заблокирован", code="user_blocked")

    empty = [key for key, value in profile.items() if value and not getattr(user, key)]
    if empty:
        for key in empty:
            setattr(user, key, profile[key])
        user.save(update_fields=empty)
    return user, False


def staff_login(raw_phone: str, password: str) -> AuthResult:
    """Вход сотрудника в панели — телефон и пароль.

    Ответ на неверный пароль, чужой номер и клиентский номер один и тот
    же: иначе по ответу можно было бы собрать список номеров сотрудников.
    Номер закрывается после `MAX_FAILURES` неверных попыток на
    `LOCK_MINUTES` — с любого адреса: лимит DRF держит перебор только с
    одного IP.
    """
    phone = normalize_phone(raw_phone)
    conf = settings.STAFF_LOGIN
    key = f"staff-login-failures:{phone}"
    if cache.get(key, 0) >= conf["MAX_FAILURES"]:
        raise RateLimitError(
            f"Слишком много неверных попыток. Попробуйте через {conf['LOCK_MINUTES']} минут.",
            code="login_locked",
        )

    user = User.objects.filter(phone=phone).first()
    if user is None:
        # Хешируем впустую: без этого несуществующий номер отвечал бы
        # заметно быстрее, и список сотрудников собирался бы по времени.
        make_password(password)
        ok = False
    else:
        ok = user.check_password(password) and user.role != UserRole.CLIENT and user.is_active

    if not ok:
        # add + incr атомарны в Redis: параллельный перебор не проскочит
        # между чтением и записью счётчика.
        cache.add(key, 0, timeout=conf["LOCK_MINUTES"] * 60)
        cache.incr(key)
        logger.warning("Неверный вход сотрудника %s", mask_phone(phone))
        raise ValidationError("Неверный телефон или пароль", code="invalid_credentials")

    cache.delete(key)
    tokens = issue_tokens(user)
    logger.info("Вход сотрудника %s", mask_phone(phone))
    return AuthResult(user=user, is_new_user=False, **tokens)


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
