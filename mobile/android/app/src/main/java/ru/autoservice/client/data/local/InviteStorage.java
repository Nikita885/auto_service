package ru.autoservice.client.data.local;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.Locale;

/**
 * Код приглашения, полученный по ссылке или из Google Play, до того как
 * им воспользовалось веб-приложение.
 *
 * <p>Между переходом по ссылке и привязкой стоит вход, а ответ магазина
 * (Install Referrer) приходит уже после старта страницы. Держать код в
 * памяти нельзя — приложение по дороге может быть выгружено системой, и
 * приглашение потеряется молча. Страница забирает код через мост и сама
 * говорит, когда он обработан.
 *
 * <p>Обычные {@link SharedPreferences}, а не шифрованные: код приглашения
 * не секрет, его печатают на странице и показывают QR-кодом.
 */
public final class InviteStorage {

    private static final String FILE = "invite";
    private static final String KEY_CODE = "pending_code";

    private final SharedPreferences prefs;

    public InviteStorage(@NonNull Context context) {
        this.prefs = context.getApplicationContext()
                .getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    /** Запомнить код. Приводим к верхнему регистру сразу. */
    public void remember(@NonNull String code) {
        String value = code.trim().toUpperCase(Locale.ROOT);
        if (!value.isEmpty()) {
            prefs.edit().putString(KEY_CODE, value).apply();
        }
    }

    @Nullable
    public String pending() {
        String value = prefs.getString(KEY_CODE, "");
        return value == null || value.isEmpty() ? null : value;
    }

    /** Код обработан — принят сервером или отклонён: он одноразовый. */
    public void clear() {
        prefs.edit().remove(KEY_CODE).apply();
    }
}
