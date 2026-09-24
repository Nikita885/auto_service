package ru.autoservice.client;

import ru.autoservice.client.util.InstallReferrer;

import android.app.Application;

import androidx.annotation.NonNull;

/**
 * Точка сборки приложения.
 *
 * <p>Зависимости собираются вручную в {@link AppContainer}, без DI-фреймворка:
 * экранов немного, граф плоский, а явная сборка читается без знания магии
 * аннотаций. Когда модулей станет больше — контейнер легко заменить на Hilt,
 * потому что экраны видят только интерфейсы репозиториев.
 */
public class App extends Application {

    private AppContainer container;

    @Override
    public void onCreate() {
        super.onCreate();
        container = new AppContainer(this);
        // Установили из Google Play по ссылке-приглашению — забираем код.
        InstallReferrer.check(this);
    }

    @NonNull
    public AppContainer container() {
        return container;
    }

    @NonNull
    public static AppContainer container(@NonNull android.content.Context context) {
        return ((App) context.getApplicationContext()).container();
    }
}
