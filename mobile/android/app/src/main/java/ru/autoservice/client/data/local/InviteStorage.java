package ru.autoservice.client.data.local;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.Locale;

/**
 * Код приглашения, полученный по ссылке, до того как им можно
 * воспользоваться.
 *
 * <p>Между переходом по ссылке и привязкой стоит целый вход по SMS:
 * человек нажал на приглашение в мессенджере, а привязать код можно
 * только авторизованному. Держать его в памяти нельзя — приложение по
 * дороге может быть выгружено системой, и приглашение потеряется молча.
 *
 * <p>Обычные {@link SharedPreferences}, а не шифрованные: код приглашения
 * не секрет, его печатают на странице и показывают QR-кодом. Шифровать
 * его — создавать видимость защиты там, где защищать нечего.
 */
public final class InviteStorage {

    private static final String FILE = "invite";
    private static final String KEY_CODE = "pending_code";

    private final SharedPreferences prefs;

    public InviteStorage(@NonNull Context context) {
        this.prefs = context.getApplicationContext()
                .getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    /** Запомнить код из ссылки. Приводим к верхнему регистру сразу. */
    public void remember(@NonNull String code) {
        String value = code.trim().toUpperCase(Locale.ROOT);
        if (value.isEmpty()) {
            return;
        }
        prefs.edit().putString(KEY_CODE, value).apply();
    }

    @Nullable
    public String pending() {
        String value = prefs.getString(KEY_CODE, "");
        return value == null || value.isEmpty() ? null : value;
    }

    /**
     * Забыть код. Вызывается и при успешной привязке, и при отказе: код
     * одноразовый, и вечно подставлять отклонённое приглашение в поле
     * ввода — значит мешать человеку вписать другое.
     */
    public void clear() {
        prefs.edit().remove(KEY_CODE).apply();
    }
}
