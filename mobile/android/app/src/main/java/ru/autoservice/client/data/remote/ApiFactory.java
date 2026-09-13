package ru.autoservice.client.data.remote;

import androidx.annotation.NonNull;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

import okhttp3.HttpUrl;
import okhttp3.Interceptor;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;
import ru.autoservice.client.BuildConfig;
import ru.autoservice.client.data.local.ServerConfig;
import ru.autoservice.client.data.local.TokenStorage;
import ru.autoservice.client.data.remote.dto.Dtos;

/**
 * Сборка HTTP-клиента: подстановка токена, молчаливое обновление access
 * и разумные таймауты.
 */
public final class ApiFactory {

    /** Доступ живёт час; при 401 обновляем его и повторяем запрос ровно один раз. */
    private static final String HEADER_AUTH = "Authorization";
    private static final String HEADER_RETRY = "X-Token-Retry";

    private ApiFactory() {
    }

    @NonNull
    public static ApiService create(@NonNull TokenStorage storage, @NonNull ServerConfig config) {
        OkHttpClient client = new OkHttpClient.Builder()
                .connectTimeout(15, TimeUnit.SECONDS)
                .readTimeout(20, TimeUnit.SECONDS)
                .writeTimeout(20, TimeUnit.SECONDS)
                .retryOnConnectionFailure(true)
                .addInterceptor(new HostInterceptor(config))
                .addInterceptor(new AuthInterceptor(storage))
                .addInterceptor(new TokenRefreshInterceptor(storage, config))
                .addInterceptor(logging())
                .build();

        return new Retrofit.Builder()
                .baseUrl(BuildConfig.API_BASE_URL)
                .client(client)
                .addConverterFactory(GsonConverterFactory.create())
                .build()
                .create(ApiService.class);
    }

    /**
     * Логи тел запросов включаются только в отладочной сборке: иначе в logcat
     * уезжали бы токены, телефоны и коды из SMS.
     */
    private static HttpLoggingInterceptor logging() {
        HttpLoggingInterceptor interceptor = new HttpLoggingInterceptor();
        interceptor.setLevel(BuildConfig.DEBUG
                ? HttpLoggingInterceptor.Level.BODY
                : HttpLoggingInterceptor.Level.NONE);
        return interceptor;
    }

    /**
     * Направляет запрос на текущий адрес сервера.
     *
     * <p>Retrofit требует базовый адрес при создании и потом его не меняет.
     * Пересоздавать весь стек ради смены хоста — значит терять пул соединений
     * и путаться в том, какой экран держит какой клиент. Проще подменить
     * схему, хост и порт у каждого запроса: путь и параметры остаются свои.
     */
    private static final class HostInterceptor implements Interceptor {

        private final ServerConfig config;

        HostInterceptor(ServerConfig config) {
            this.config = config;
        }

        @NonNull
        @Override
        public Response intercept(@NonNull Chain chain) throws IOException {
            Request request = chain.request();
            HttpUrl target = HttpUrl.parse(config.baseUrl());
            if (target == null) {
                return chain.proceed(request);
            }

            HttpUrl url = request.url().newBuilder()
                    .scheme(target.scheme())
                    .host(target.host())
                    .port(target.port())
                    .build();

            return chain.proceed(request.newBuilder().url(url).build());
        }
    }

    /** Подставляет access-токен во все запросы, кроме публичных. */
    private static final class AuthInterceptor implements Interceptor {

        private final TokenStorage storage;

        AuthInterceptor(TokenStorage storage) {
            this.storage = storage;
        }

        @NonNull
        @Override
        public Response intercept(@NonNull Chain chain) throws IOException {
            Request request = chain.request();
            String token = storage.accessToken();

            // На эндпоинты входа токен слать нечего и незачем.
            boolean isAuthCall = request.url().encodedPath().contains("/auth/otp/")
                    || request.url().encodedPath().contains("/auth/token/refresh/");

            if (token == null || isAuthCall) {
                return chain.proceed(request);
            }
            return chain.proceed(request.newBuilder()
                    .header(HEADER_AUTH, "Bearer " + token)
                    .build());
        }
    }

    /**
     * Ловит 401, меняет access по refresh и повторяет исходный запрос.
     *
     * <p>Без этого вкладка, открытая с утра, начинала бы сыпать ошибками через
     * час. Повтор строго один: если и он получил 401, значит refresh мёртв —
     * токены чистятся, и приложение попросит войти заново.
     */
    private static final class TokenRefreshInterceptor implements Interceptor {

        private static final Object REFRESH_LOCK = new Object();

        private final TokenStorage storage;
        private final ServerConfig config;

        TokenRefreshInterceptor(TokenStorage storage, ServerConfig config) {
            this.storage = storage;
            this.config = config;
        }

        /** Клиент без перехватчиков — только для обмена refresh на новую пару. */
        private static Retrofit plainRetrofit(@NonNull HttpUrl baseUrl) {
            return new Retrofit.Builder()
                    .baseUrl(baseUrl)
                    .client(new OkHttpClient.Builder()
                            .connectTimeout(15, TimeUnit.SECONDS)
                            .readTimeout(20, TimeUnit.SECONDS)
                            .build())
                    .addConverterFactory(GsonConverterFactory.create())
                    .build();
        }

        @NonNull
        @Override
        public Response intercept(@NonNull Chain chain) throws IOException {
            Request request = chain.request();
            Response response = chain.proceed(request);

            if (response.code() != 401 || request.header(HEADER_RETRY) != null) {
                return response;
            }

            String refresh = storage.refreshToken();
            if (refresh == null) {
                storage.clearTokens();
                return response;
            }

            response.close();

            String newAccess;
            // Параллельные запросы не должны обновлять токен одновременно:
            // сервер ротирует refresh, и второй обмен получил бы уже
            // отозванный токен.
            synchronized (REFRESH_LOCK) {
                String current = storage.accessToken();
                String requestToken = request.header(HEADER_AUTH);
                boolean alreadyRefreshed = current != null && requestToken != null
                        && !requestToken.endsWith(current);

                newAccess = alreadyRefreshed ? current : exchange(refresh);
            }

            if (newAccess == null) {
                storage.clearTokens();
                return chain.proceed(request.newBuilder().header(HEADER_RETRY, "1").build());
            }

            return chain.proceed(request.newBuilder()
                    .header(HEADER_AUTH, "Bearer " + newAccess)
                    .header(HEADER_RETRY, "1")
                    .build());
        }

        /**
         * Обмен refresh на новую пару.
         *
         * <p>Отдельный клиент без перехватчиков: иначе обновление токена
         * попало бы в собственную обработку 401 и зациклилось. Адрес берётся
         * из настройки — тот же, куда ушёл исходный запрос.
         */
        private String exchange(@NonNull String refresh) {
            try {
                HttpUrl baseUrl = HttpUrl.parse(config.baseUrl());
                if (baseUrl == null) {
                    return null;
                }
                ApiService plain = plainRetrofit(baseUrl).create(ApiService.class);

                retrofit2.Response<Dtos.RefreshResponse> result =
                        plain.refreshToken(new Dtos.RefreshBody(refresh)).execute();

                if (!result.isSuccessful() || result.body() == null) {
                    return null;
                }
                Dtos.RefreshResponse body = result.body();
                storage.saveTokens(body.access, body.refresh);
                return body.access;
            } catch (IOException | RuntimeException e) {
                return null;
            }
        }
    }
}
