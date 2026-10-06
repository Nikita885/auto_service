package ru.autoservice.client;

import android.app.Application;
import android.content.Context;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import ru.autoservice.client.data.local.InviteStorage;
import ru.autoservice.client.data.local.TokenStorage;
import ru.autoservice.client.util.InstallReferrer;

/**
 * Приложение — оболочка над веб-приложением `/app/` (то же, что на iPhone).
 *
 * <p>Здесь живут только два хранилища, которые нужны и оболочке, и тому,
 * что приходит снаружи (ссылка-приглашение, Google Play): токены входа и
 * отложенный код приглашения.
 */
public class App extends Application {

    private TokenStorage tokens;
    private InviteStorage invites;
    @Nullable private Runnable inviteListener;

    @Override
    public void onCreate() {
        super.onCreate();
        tokens = new TokenStorage(this);
        invites = new InviteStorage(this);
        // Установили из Google Play по ссылке-приглашению — забираем код.
        InstallReferrer.check(this);
    }

    @NonNull
    public static TokenStorage tokens(@NonNull Context context) {
        return ((App) context.getApplicationContext()).tokens;
    }

    @NonNull
    public static InviteStorage invites(@NonNull Context context) {
        return ((App) context.getApplicationContext()).invites;
    }

    /** Экран, которому сказать «пришёл код приглашения», или null. */
    public static void setInviteListener(@NonNull Context context, @Nullable Runnable listener) {
        ((App) context.getApplicationContext()).inviteListener = listener;
    }

    /** Код отложен (ссылка, Google Play) — сообщить открытому экрану. */
    public static void inviteArrived(@NonNull Context context) {
        Runnable listener = ((App) context.getApplicationContext()).inviteListener;
        if (listener != null) {
            listener.run();
        }
    }
}
