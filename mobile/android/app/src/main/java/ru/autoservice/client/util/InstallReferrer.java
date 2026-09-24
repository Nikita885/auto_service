package ru.autoservice.client.util;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;

import com.android.installreferrer.api.InstallReferrerClient;
import com.android.installreferrer.api.InstallReferrerStateListener;

import ru.autoservice.client.App;

/**
 * Код приглашения, с которым приложение установили из Google Play.
 *
 * <p>Сценарий: друг прислал ссылку `/i/<код>`, приложения у человека ещё
 * нет. Сайт ведёт его в Google Play со ссылкой, в которую вложен
 * `referrer=invite=<код>`. После установки Play отдаёт этот параметр
 * приложению — и код оказывается там же, где код из открытой ссылки:
 * уйдёт на сервер вместе со входом, вводить ничего не придётся.
 *
 * <p>Спрашиваем один раз за жизнь установки: параметр от Play не меняется,
 * а подключение к сервису магазина на каждом запуске — лишняя работа.
 */
public final class InstallReferrer {

    private static final String PREFS = "install_referrer";
    private static final String KEY_CHECKED = "checked";

    private InstallReferrer() {
    }

    public static void check(@NonNull Context context) {
        Context app = context.getApplicationContext();
        SharedPreferences prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (prefs.getBoolean(KEY_CHECKED, false)) {
            return;
        }

        InstallReferrerClient client = InstallReferrerClient.newBuilder(app).build();
        try {
            client.startConnection(new InstallReferrerStateListener() {
                @Override
                public void onInstallReferrerSetupFinished(int responseCode) {
                    try {
                        if (responseCode == InstallReferrerClient.InstallReferrerResponse.OK) {
                            String code = InviteCodes.fromReferrer(
                                    client.getInstallReferrer().getInstallReferrer());
                            if (code != null) {
                                App.container(app).invites().remember(code);
                            }
                        }
                        // Недоступен магазин (сборка не из Play, эмулятор) — тоже
                        // окончательный ответ: спрашивать снова бессмысленно.
                        if (responseCode != InstallReferrerClient.InstallReferrerResponse.SERVICE_DISCONNECTED) {
                            prefs.edit().putBoolean(KEY_CHECKED, true).apply();
                        }
                    } catch (Exception ignored) {
                        // Параметр установки — удобство, а не условие работы.
                    } finally {
                        client.endConnection();
                    }
                }

                @Override
                public void onInstallReferrerServiceDisconnected() {
                    // Попробуем при следующем запуске.
                }
            });
        } catch (Exception ignored) {
            // Нет сервисов Google Play — приложение работает и без этого.
        }
    }
}
