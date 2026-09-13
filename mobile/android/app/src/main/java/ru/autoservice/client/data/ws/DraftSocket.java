package ru.autoservice.client.data.ws;

import android.os.Handler;
import android.os.Looper;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.gson.Gson;
import com.google.gson.JsonSyntaxException;

import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import ru.autoservice.client.data.local.ServerConfig;
import ru.autoservice.client.data.local.TokenStorage;
import ru.autoservice.client.data.remote.DtoMapper;
import ru.autoservice.client.data.remote.dto.Dtos;
import ru.autoservice.client.domain.model.Models;

/**
 * Живой статус записи.
 *
 * <p>Канал только ускоряет обновление: то же состояние доступно через
 * REST-эндпоинт текущего черновика. Если WebSocket недоступен — в корпоративной
 * сети, за прокси, на плохом мобильном — экран продолжает работать, поэтому
 * ошибки соединения не показываются пользователю.
 *
 * <p>Токен передаётся в query-строке: браузерный контракт сервера общий для
 * всех клиентов, отдельного заголовка он не ждёт. По этой же причине в
 * релизе адрес обязан быть wss — иначе токен уйдёт открытым текстом.
 */
public final class DraftSocket {

    private static final int CLOSE_NORMAL = 1000;
    /** Пауза перед повтором: канал вспомогательный, дёргать сервер незачем. */
    private static final long RECONNECT_DELAY_MS = 5_000L;

    private final OkHttpClient client;
    private final TokenStorage storage;
    private final ServerConfig config;
    private final Gson gson = new Gson();
    private final Handler main = new Handler(Looper.getMainLooper());

    @Nullable private WebSocket socket;
    @Nullable private Listener listener;
    private boolean stopped = true;

    public DraftSocket(@NonNull TokenStorage storage, @NonNull ServerConfig config) {
        this.storage = storage;
        this.config = config;
        this.client = new OkHttpClient.Builder()
                .connectTimeout(15, TimeUnit.SECONDS)
                // Пинг держит соединение живым через NAT и мобильных операторов.
                .pingInterval(25, TimeUnit.SECONDS)
                .build();
    }

    /** События канала. Приходят в главный поток. */
    public interface Listener {
        /** Состояние черновика изменилось: создан, пройден шаг, истёк, закрыт. */
        void onDraftChanged(@Nullable Models.Draft draft);

        /** Появилась или изменилась запись — список своих броней устарел. */
        void onBookingChanged();
    }

    public void start(@NonNull Listener listener) {
        this.listener = listener;
        this.stopped = false;
        connect();
    }

    public void stop() {
        stopped = true;
        listener = null;
        main.removeCallbacksAndMessages(null);
        if (socket != null) {
            socket.close(CLOSE_NORMAL, null);
            socket = null;
        }
    }

    private void connect() {
        String token = storage.accessToken();
        if (stopped || token == null) {
            return;
        }

        Request request = new Request.Builder()
                .url(config.webSocketUrl() + "ws/booking/?token=" + token)
                .build();

        socket = client.newWebSocket(request, new WebSocketListener() {
            @Override
            public void onMessage(@NonNull WebSocket webSocket, @NonNull String text) {
                handle(text);
            }

            @Override
            public void onFailure(@NonNull WebSocket webSocket, @NonNull Throwable t,
                                  @Nullable Response response) {
                scheduleReconnect();
            }

            @Override
            public void onClosed(@NonNull WebSocket webSocket, int code, @NonNull String reason) {
                if (code != CLOSE_NORMAL) {
                    scheduleReconnect();
                }
            }
        });
    }

    private void scheduleReconnect() {
        if (stopped) {
            return;
        }
        socket = null;
        main.postDelayed(this::connect, RECONNECT_DELAY_MS);
    }

    private void handle(@NonNull String text) {
        Dtos.SocketEvent event;
        try {
            event = gson.fromJson(text, Dtos.SocketEvent.class);
        } catch (JsonSyntaxException e) {
            return;
        }
        if (event == null || event.event == null) {
            return;
        }

        main.post(() -> {
            Listener current = listener;
            if (current == null) {
                return;
            }
            if (event.event.startsWith("draft.")) {
                // draft.absent приходит с пустым payload — это «записи нет».
                current.onDraftChanged(DtoMapper.draft(event.payload));
            } else if (event.event.startsWith("booking.")) {
                current.onBookingChanged();
            }
        });
    }
}
