package ru.autoservice.client.data.local;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import ru.autoservice.client.BuildConfig;

/**
 * Адрес сервера, к которому подключается приложение.
 *
 * <p>По умолчанию берётся из сборки, но в отладочной версии его можно сменить
 * прямо в приложении. Так нужно, потому что адрес dev-сервера живёт недолго:
 * туннель наружу выдаёт новое имя при каждом перезапуске, и пересобирать APK
 * ради одной строки — потерянные минуты на каждый тест.
 *
 * <p>Секрета тут нет, поэтому обычные настройки, а не шифрованные: адрес
 * сервера и так виден в трафике.
 */
public final class ServerConfig {

    private static final String FILE = "server_config";
    private static final String KEY_BASE_URL = "base_url";

    private final SharedPreferences prefs;

    public ServerConfig(@NonNull Context context) {
        this.prefs = context.getApplicationContext()
                .getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    /** Базовый адрес API со слешем на конце: {@code https://example.com/}. */
    @NonNull
    public String baseUrl() {
        String saved = prefs.getString(KEY_BASE_URL, null);
        return saved == null ? BuildConfig.API_BASE_URL : saved;
    }

    /**
     * Адрес WebSocket-канала.
     *
     * <p>Выводится из основного, а не хранится отдельно: держать два адреса —
     * значит однажды поменять один и забыть второй.
     */
    @NonNull
    public String webSocketUrl() {
        String saved = prefs.getString(KEY_BASE_URL, null);
        if (saved == null) {
            return BuildConfig.WS_BASE_URL;
        }
        if (saved.startsWith("https://")) {
            return "wss://" + saved.substring("https://".length());
        }
        if (saved.startsWith("http://")) {
            return "ws://" + saved.substring("http://".length());
        }
        return saved;
    }

    /** Адрес задан вручную, а не взят из сборки. */
    public boolean isCustom() {
        return prefs.getString(KEY_BASE_URL, null) != null;
    }

    /**
     * Сохранить адрес. Пустое значение возвращает адрес из сборки.
     *
     * <p>Строка приводится к виду, который ждёт OkHttp: схема обязательна,
     * слеш на конце тоже — иначе относительные пути склеятся неправильно.
     */
    public void save(@Nullable String rawUrl) {
        String value = rawUrl == null ? "" : rawUrl.trim();

        if (value.isEmpty()) {
            prefs.edit().remove(KEY_BASE_URL).apply();
            return;
        }

        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            // Без схемы считаем, что это туннель или домен: наружу ходим по https.
            value = "https://" + value;
        }
        if (!value.endsWith("/")) {
            value = value + "/";
        }

        prefs.edit().putString(KEY_BASE_URL, value).apply();
    }
}
