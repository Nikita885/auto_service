package ru.autoservice.client.shell;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.webkit.JavascriptInterface;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import ru.autoservice.client.App;
import ru.autoservice.client.R;
import ru.autoservice.client.data.local.InviteStorage;
import ru.autoservice.client.data.local.TokenStorage;

/**
 * Мост страницы к приложению: `window.MoiServisNative` в веб-приложении.
 *
 * <p>Методы вызываются из JS на служебном потоке WebView, поэтому всё, что
 * трогает интерфейс, уходит в главный поток, а состояние — `volatile`.
 *
 * <p><b>Мост виден любой странице в WebView</b>, поэтому каждый метод
 * сначала проверяет {@link #trusted}: оболочка ставит его, только когда
 * открыт адрес веб-приложения на своём домене ({@link ShellPolicy}). Чужие
 * адреса в оболочке и не открываются — уходят в браузер, — проверка здесь
 * на случай, если это однажды сломают.
 */
final class NativeBridge {

    static final String NAME = "MoiServisNative";

    private final Activity activity;
    private final TokenStorage tokens;
    private final InviteStorage invites;

    volatile boolean trusted;
    volatile String insetsJson = "{\"top\":0,\"bottom\":0}";

    NativeBridge(@NonNull Activity activity) {
        this.activity = activity;
        this.tokens = App.tokens(activity);
        this.invites = App.invites(activity);
    }

    // ------------------------------------------------------ хранилище токенов
    // Интерфейс localStorage: core.js подставляет мост вместо него.

    @JavascriptInterface
    @Nullable
    public String getItem(@Nullable String key) {
        String own = trusted ? ShellPolicy.storageKey(key) : null;
        return own == null ? null : tokens.get(own);
    }

    @JavascriptInterface
    public void setItem(@Nullable String key, @Nullable String value) {
        String own = trusted ? ShellPolicy.storageKey(key) : null;
        if (own != null) {
            tokens.put(own, value);
        }
    }

    @JavascriptInterface
    public void removeItem(@Nullable String key) {
        setItem(key, null);
    }

    // --------------------------------------------------------- приглашение

    @JavascriptInterface
    @Nullable
    public String pendingInvite() {
        return trusted ? invites.pending() : null;
    }

    @JavascriptInterface
    public void clearInvite() {
        if (trusted) {
            invites.clear();
        }
    }

    // ------------------------------------------------- системные возможности

    /** Системное меню «Поделиться» — в WebView `navigator.share` нет. */
    @JavascriptInterface
    public void share(@Nullable String text) {
        if (!trusted || text == null || text.isEmpty()) {
            return;
        }
        activity.runOnUiThread(() -> {
            Intent send = new Intent(Intent.ACTION_SEND)
                    .setType("text/plain")
                    .putExtra(Intent.EXTRA_TEXT, text);
            activity.startActivity(Intent.createChooser(send, activity.getString(R.string.share_title)));
        });
    }

    /** Буфер обмена: `navigator.clipboard` в WebView работает не везде. */
    @JavascriptInterface
    public boolean copy(@Nullable String text) {
        if (!trusted || text == null) {
            return false;
        }
        ClipboardManager clipboard =
                (ClipboardManager) activity.getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard == null) {
            return false;
        }
        clipboard.setPrimaryClip(ClipData.newPlainText(activity.getString(R.string.app_name), text));
        return true;
    }

    /**
     * Текст из буфера обмена — для «Вставить код приглашения». Читаем только
     * по нажатию человека на странице (её кнопка зовёт этот метод), и только
     * своей странице: буфер — чужие данные.
     */
    @JavascriptInterface
    @Nullable
    public String paste() {
        if (!trusted) {
            return null;
        }
        ClipboardManager clipboard =
                (ClipboardManager) activity.getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard == null || !clipboard.hasPrimaryClip()) {
            return null;
        }
        ClipData clip = clipboard.getPrimaryClip();
        if (clip == null || clip.getItemCount() == 0) {
            return null;
        }
        CharSequence text = clip.getItemAt(0).coerceToText(activity);
        return text == null ? null : text.toString();
    }

    /** Отступы под системные панели в CSS-пикселях: `{"top":24,"bottom":48}`. */
    @JavascriptInterface
    @NonNull
    public String insets() {
        return insetsJson;
    }
}
