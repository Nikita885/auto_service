package ru.autoservice.client.data.local;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKeys;

import java.io.IOException;
import java.security.GeneralSecurityException;

/**
 * Хранилище токенов входа.
 *
 * <p>Лежит в {@link EncryptedSharedPreferences}: ключ шифрования живёт в
 * Android Keystore и не покидает устройство. На рутованном телефоне или при
 * снятии бэкапа обычный XML с токенами (и localStorage WebView) читается как
 * открытый текст, а refresh-токен живёт 30 дней — этого достаточно, чтобы
 * войти в чужой аккаунт.
 *
 * <p>Файл и ключи те же, что у прежнего нативного клиента: после обновления
 * на оболочку человек остаётся в аккаунте, а не входит заново.
 *
 * <p>Используется API стабильной версии security-crypto 1.0.0. Класс
 * {@code MasterKeys} в ней помечен устаревшим, а пришедший ему на смену
 * {@code MasterKey.Builder} есть только в ветке 1.1.0-alpha — тянуть альфу в
 * приложение, которое пойдёт в Play, не стоит.
 *
 * <p>Если хранилище не поднялось (редкий сбой Keystore после обновления
 * прошивки), мы не падаем и не скатываемся в незашифрованные настройки:
 * приложение просто попросит войти заново.
 */
public final class TokenStorage {

    private static final String FILE = "auth_tokens";

    @Nullable private final SharedPreferences prefs;

    public TokenStorage(@NonNull Context context) {
        this.prefs = createEncrypted(context.getApplicationContext());
    }

    @Nullable
    @SuppressWarnings("deprecation") // см. комментарий к классу
    private static SharedPreferences createEncrypted(@NonNull Context context) {
        try {
            String masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC);
            return EncryptedSharedPreferences.create(
                    FILE,
                    masterKeyAlias,
                    context,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM);
        } catch (GeneralSecurityException | IOException e) {
            // Осознанно молча: в лог нельзя, а падать из-за этого нельзя тем более.
            return null;
        }
    }

    @Nullable
    public synchronized String get(@NonNull String key) {
        return prefs == null ? null : prefs.getString(key, null);
    }

    public synchronized void put(@NonNull String key, @Nullable String value) {
        if (prefs == null) {
            return;
        }
        if (value == null || value.isEmpty()) {
            prefs.edit().remove(key).apply();
        } else {
            prefs.edit().putString(key, value).apply();
        }
    }
}
