package ru.autoservice.client.data.remote;

import android.os.Handler;
import android.os.Looper;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.gson.Gson;
import com.google.gson.JsonSyntaxException;

import java.io.IOException;

import okhttp3.ResponseBody;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;
import ru.autoservice.client.data.remote.dto.Dtos;
import ru.autoservice.client.util.ApiError;
import ru.autoservice.client.util.Result;

/**
 * Мост между Retrofit и {@link Result}.
 *
 * <p>Здесь, и только здесь, HTTP превращается в результат операции: дальше по
 * коду нет ни кодов ответа, ни {@code IOException}. Разбор конверта ошибки
 * тоже живёт тут — формат у сервера один на все эндпоинты.
 */
public final class Calls {

    private static final Gson GSON = new Gson();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private Calls() {
    }

    /** Простой вызов: тело ответа отдаётся как есть. */
    public static <T> void enqueue(@NonNull Call<T> call, @NonNull Result.Callback<T> callback) {
        enqueue(call, value -> value, callback);
    }

    /**
     * Вызов с преобразованием: DTO превращается в доменную модель прямо здесь,
     * чтобы наружу репозитория транспортные типы не выходили.
     */
    public static <D, T> void enqueue(@NonNull Call<D> call,
                                      @NonNull Mapper<D, T> mapper,
                                      @NonNull Result.Callback<T> callback) {
        call.enqueue(new Callback<D>() {
            @Override
            public void onResponse(@NonNull Call<D> call, @NonNull Response<D> response) {
                if (!response.isSuccessful()) {
                    deliver(callback, Result.failure(parseError(response)));
                    return;
                }
                // 204 — законный ответ «ничего нет» (например, черновика).
                D body = response.body();
                try {
                    deliver(callback, Result.success(body == null ? null : mapper.map(body)));
                } catch (RuntimeException e) {
                    deliver(callback, Result.failure(ApiError.unknown(response.code())));
                }
            }

            @Override
            public void onFailure(@NonNull Call<D> call, @NonNull Throwable t) {
                // Сюда попадают обрывы связи и таймауты — до сервера не дошли.
                deliver(callback, Result.failure(
                        t instanceof IOException ? ApiError.network() : ApiError.unknown(0)));
            }
        });
    }

    @NonNull
    private static ApiError parseError(@NonNull Response<?> response) {
        if (response.code() == 401) {
            return ApiError.unauthorized();
        }

        ResponseBody errorBody = response.errorBody();
        if (errorBody == null) {
            return ApiError.unknown(response.code());
        }

        try {
            Dtos.ErrorEnvelope envelope = GSON.fromJson(errorBody.string(), Dtos.ErrorEnvelope.class);
            if (envelope == null || envelope.error == null || envelope.error.code == null) {
                return ApiError.unknown(response.code());
            }

            Integer retryAfter = null;
            Integer attemptsLeft = null;
            if (envelope.error.details != null) {
                retryAfter = envelope.error.details.retryAfter;
                attemptsLeft = envelope.error.details.attemptsLeft;
            }

            return new ApiError(
                    envelope.error.code,
                    envelope.error.message == null ? "" : envelope.error.message,
                    response.code(),
                    retryAfter,
                    attemptsLeft);
        } catch (IOException | JsonSyntaxException e) {
            return ApiError.unknown(response.code());
        }
    }

    private static <T> void deliver(@NonNull Result.Callback<T> callback, @NonNull Result<T> result) {
        // Колбэки Retrofit и так приходят в главный поток, но контракт лучше
        // держать явным: репозиторий обещает главный поток, а не «как получится».
        if (Looper.myLooper() == Looper.getMainLooper()) {
            callback.onResult(result);
        } else {
            MAIN.post(() -> callback.onResult(result));
        }
    }

    /** Преобразование DTO в доменную модель. */
    public interface Mapper<D, T> {
        @Nullable
        T map(@NonNull D dto);
    }
}
