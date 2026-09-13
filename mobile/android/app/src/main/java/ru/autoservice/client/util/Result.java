package ru.autoservice.client.util;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

/**
 * Результат операции: либо значение, либо ошибка.
 *
 * <p>Исключения наружу из репозиториев не летят: вызывающий код обязан
 * разобрать оба исхода, и «забыть про ошибку» становится невозможно.
 */
public final class Result<T> {

    @Nullable private final T value;
    @Nullable private final ApiError error;

    private Result(@Nullable T value, @Nullable ApiError error) {
        this.value = value;
        this.error = error;
    }

    public static <T> Result<T> success(@Nullable T value) {
        return new Result<>(value, null);
    }

    public static <T> Result<T> failure(@NonNull ApiError error) {
        return new Result<>(null, error);
    }

    public boolean isSuccess() {
        return error == null;
    }

    /** Значение успешного результата. У неуспешного — null. */
    @Nullable
    public T value() {
        return value;
    }

    @Nullable
    public ApiError error() {
        return error;
    }

    /** Колбэк репозитория. Вызывается в главном потоке. */
    public interface Callback<T> {
        void onResult(@NonNull Result<T> result);
    }
}
