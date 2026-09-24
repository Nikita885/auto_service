package ru.autoservice.client;

import android.content.Context;

import androidx.annotation.NonNull;

import ru.autoservice.client.data.local.InviteStorage;
import ru.autoservice.client.data.local.ServerConfig;
import ru.autoservice.client.data.local.TokenStorage;
import ru.autoservice.client.data.remote.ApiFactory;
import ru.autoservice.client.data.remote.ApiService;
import ru.autoservice.client.data.repository.AuthRepository;
import ru.autoservice.client.data.repository.BookingRepository;
import ru.autoservice.client.data.repository.CarsRepository;
import ru.autoservice.client.data.repository.ReferralRepository;
import ru.autoservice.client.data.ws.DraftSocket;

/**
 * Контейнер зависимостей уровня приложения.
 *
 * <p>Всё здесь живёт столько же, сколько процесс: HTTP-клиент дорого
 * пересоздавать, а хранилище токенов должно быть одно на всех — иначе
 * обновление токена в одном экране не увидит другой.
 */
public final class AppContainer {

    private final TokenStorage tokenStorage;
    private final ServerConfig serverConfig;
    private final InviteStorage inviteStorage;
    private final ApiService api;
    private final AuthRepository authRepository;
    private final BookingRepository bookingRepository;
    private final ReferralRepository referralRepository;
    private final CarsRepository carsRepository;

    AppContainer(@NonNull Context context) {
        this.tokenStorage = new TokenStorage(context);
        this.serverConfig = new ServerConfig(context);
        this.inviteStorage = new InviteStorage(context);
        this.api = ApiFactory.create(tokenStorage, serverConfig);
        this.authRepository = new AuthRepository(api, tokenStorage, inviteStorage);
        this.bookingRepository = new BookingRepository(api);
        this.referralRepository = new ReferralRepository(api);
        this.carsRepository = new CarsRepository(api);
    }

    @NonNull
    public AuthRepository auth() {
        return authRepository;
    }

    @NonNull
    public BookingRepository booking() {
        return bookingRepository;
    }

    @NonNull
    public ReferralRepository referral() {
        return referralRepository;
    }

    @NonNull
    public CarsRepository cars() {
        return carsRepository;
    }

    /**
     * Код приглашения, пришедший по ссылке, пока им нельзя
     * воспользоваться: между переходом по ссылке и привязкой стоит вход.
     */
    @NonNull
    public InviteStorage invites() {
        return inviteStorage;
    }

    /**
     * Канал живого статуса. Создаётся под каждый экран: подписка привязана к
     * жизненному циклу, и общий на всё приложение сокет пришлось бы вручную
     * открывать и закрывать при каждом переходе.
     */
    @NonNull
    public DraftSocket newDraftSocket() {
        return new DraftSocket(tokenStorage, serverConfig);
    }

    /**
     * Адрес сервера. Меняется в отладочной сборке прямо на экране входа:
     * туннель к dev-серверу выдаёт новое имя при каждом перезапуске.
     */
    @NonNull
    public ServerConfig serverConfig() {
        return serverConfig;
    }

    /** Смена сервера обесценивает выданные им токены — сессию сбрасываем. */
    public void onServerChanged() {
        tokenStorage.clearTokens();
    }
}
