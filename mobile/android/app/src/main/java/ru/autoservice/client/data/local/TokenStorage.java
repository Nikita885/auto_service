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
 * Хранилище токенов.
 *
 * <p>Лежит в {@link EncryptedSharedPreferences}: ключ шифрования живёт в
 * Android Keystore и не покидает устройство. На рутованном телефоне или при
 * снятии бэкапа обычный XML с токенами читается как открытый текст, а
 * refresh-токен живёт 30 дней — этого достаточно, чтобы войти в чужой аккаунт.
 *
 * <p>Используется API стабильной версии security-crypto 1.0.0. Класс
 * {@code MasterKeys} в ней помечен устаревшим, а пришедший ему на смену
 * {@code MasterKey.Builder} есть только в ветке 1.1.0-alpha — тянуть альфу в
 * приложение, которое пойдёт в Play, не стоит. При переходе на стабильную
 * 1.1.x замена займёт три строки вот тут.
 *
 * <p>Если хранилище по какой-то причине не поднялось (редкий сбой Keystore
 * после обновления прошивки), мы не падаем и не скатываемся в незашифрованные
 * настройки: приложение просто попросит войти заново.
 */
public final class TokenStorage {

    private static final String FILE = "auth_tokens";
    private static final String KEY_ACCESS = "access";
    private static final String KEY_REFRESH = "refresh";
    private static final String KEY_PHONE = "phone";

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
    public synchronized String accessToken() {
        return prefs == null ? null : prefs.getString(KEY_ACCESS, null);
    }

    @Nullable
    public synchronized String refreshToken() {
        return prefs == null ? null : prefs.getString(KEY_REFRESH, null);
    }

    /** Телефон последнего входа — чтобы не набирать его заново. */
    @Nullable
    public synchronized String lastPhone() {
        return prefs == null ? null : prefs.getString(KEY_PHONE, null);
    }

    public synchronized void saveTokens(@NonNull String access, @Nullable String refresh) {
        if (prefs == null) {
            return;
        }
        SharedPreferences.Editor editor = prefs.edit().putString(KEY_ACCESS, access);
        if (refresh != null && !refresh.isEmpty()) {
            editor.putString(KEY_REFRESH, refresh);
        }
        editor.apply();
    }

    public synchronized void savePhone(@NonNull String phone) {
        if (prefs != null) {
            prefs.edit().putString(KEY_PHONE, phone).apply();
        }
    }

    public synchronized boolean isSignedIn() {
        return accessToken() != null;
    }

    /** Выход: телефон оставляем, секреты стираем. */
    public synchronized void clearTokens() {
        if (prefs != null) {
            prefs.edit().remove(KEY_ACCESS).remove(KEY_REFRESH).apply();
        }
    }
}
