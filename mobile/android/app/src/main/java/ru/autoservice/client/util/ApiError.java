package ru.autoservice.client.util;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

/**
 * Ошибка API в том виде, в каком её отдаёт сервер:
 * {@code {"error": {"code": "slot_taken", "message": "…", "details": {}}}}.
 *
 * <p>Решения принимаются по машиночитаемому {@code code}, а не по тексту:
 * формулировки на сервере правят без оглядки на приложение.
 */
public final class ApiError {

    /** Сеть недоступна: запрос даже не дошёл до сервера. */
    public static final String CODE_NETWORK = "network_unavailable";
    /** Всё остальное, чего мы не ожидали. */
    public static final String CODE_UNKNOWN = "unknown";

    public static final String CODE_DRAFT_EXPIRED = "draft_expired";
    public static final String CODE_DRAFT_CLOSED = "draft_closed";
    public static final String CODE_SLOT_TAKEN = "slot_taken";
    public static final String CODE_OIL_OUT_OF_STOCK = "oil_out_of_stock";
    public static final String CODE_OTP_INVALID = "otp_invalid";
    public static final String CODE_OTP_COOLDOWN = "otp_cooldown";
    public static final String CODE_UNAUTHORIZED = "unauthorized";

    private final String code;
    private final String message;
    private final int httpStatus;
    @Nullable private final Integer retryAfterSeconds;
    @Nullable private final Integer attemptsLeft;

    public ApiError(@NonNull String code, @NonNull String message, int httpStatus,
                    @Nullable Integer retryAfterSeconds, @Nullable Integer attemptsLeft) {
        this.code = code;
        this.message = message;
        this.httpStatus = httpStatus;
        this.retryAfterSeconds = retryAfterSeconds;
        this.attemptsLeft = attemptsLeft;
    }

    public static ApiError network() {
        return new ApiError(CODE_NETWORK, "", 0, null, null);
    }

    public static ApiError unknown(int httpStatus) {
        return new ApiError(CODE_UNKNOWN, "", httpStatus, null, null);
    }

    public static ApiError unauthorized() {
        return new ApiError(CODE_UNAUTHORIZED, "", 401, null, null);
    }

    @NonNull
    public String code() {
        return code;
    }

    /** Текст с сервера. Может быть пустым — тогда показывайте свой. */
    @NonNull
    public String message() {
        return message;
    }

    public int httpStatus() {
        return httpStatus;
    }

    /** Через сколько секунд можно повторить запрос кода. */
    @Nullable
    public Integer retryAfterSeconds() {
        return retryAfterSeconds;
    }

    /** Сколько попыток ввода кода осталось. */
    @Nullable
    public Integer attemptsLeft() {
        return attemptsLeft;
    }

    public boolean is(@NonNull String expectedCode) {
        return code.equals(expectedCode);
    }

    /** Черновик умер — экран записи нужно перечитать с нуля. */
    public boolean isDraftGone() {
        return is(CODE_DRAFT_EXPIRED) || is(CODE_DRAFT_CLOSED);
    }
}
