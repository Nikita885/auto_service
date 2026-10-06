package ru.autoservice.client.shell;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.net.URI;
import java.util.Locale;

/**
 * Что оболочка считает «своим»: какие адреса открываются внутри, какие —
 * в браузере, и какие ключи хранилища страницы уходят в Keystore.
 *
 * <p>Без единой ссылки на Android: правила, ошибка в которых открывает мост
 * чужой странице, гоняются обычными JUnit-тестами ({@code ShellPolicyTest}).
 */
public final class ShellPolicy {

    /** Путь веб-приложения: всё под ним — экраны, остальное — сайт. */
    private static final String APP_PATH = "/app/";

    private final String scheme;
    private final String host;
    private final int port;
    private final String siteUrl;

    public ShellPolicy(@NonNull String siteUrl) {
        URI uri = URI.create(siteUrl);
        this.scheme = lower(uri.getScheme());
        this.host = lower(uri.getHost());
        this.port = effectivePort(uri);
        this.siteUrl = siteUrl.endsWith("/") ? siteUrl : siteUrl + "/";
    }

    /** Адрес, с которого оболочка стартует. */
    @NonNull
    public String startUrl() {
        return siteUrl + "app/";
    }

    /**
     * Открывать ли адрес внутри оболочки. Только веб-приложение на своём
     * домене и своей схеме: витрина, `/i/<код>` и чужие сайты уходят в
     * браузер, а мост к Keystore чужой странице не достаётся.
     *
     * <p>Сравнение по разобранному адресу, а не по началу строки: иначе
     * `https://moi-servis.ru.evil.example/app/` сошёл бы за свой.
     */
    public boolean isInternal(@Nullable String url) {
        if (url == null) {
            return false;
        }
        URI uri;
        try {
            uri = URI.create(url.trim());
        } catch (IllegalArgumentException e) {
            return false;
        }
        if (!scheme.equals(lower(uri.getScheme())) || !host.equals(lower(uri.getHost()))
                || port != effectivePort(uri)) {
            return false;
        }
        String path = uri.getRawPath();
        return path != null && (path.equals("/app") || path.startsWith(APP_PATH));
    }

    /**
     * Ключ localStorage страницы → ключ зашифрованного хранилища. Мост отдаёт
     * странице только токены клиента; `null` — ключ не наш, не храним.
     */
    @Nullable
    public static String storageKey(@Nullable String webKey) {
        if ("client.access".equals(webKey)) {
            return TokenKeys.ACCESS;
        }
        if ("client.refresh".equals(webKey)) {
            return TokenKeys.REFRESH;
        }
        return null;
    }

    /** Имена ключей в хранилище токенов — те же, что у прежнего клиента. */
    public static final class TokenKeys {
        public static final String ACCESS = "access";
        public static final String REFRESH = "refresh";

        private TokenKeys() {
        }
    }

    private static int effectivePort(@NonNull URI uri) {
        if (uri.getPort() != -1) {
            return uri.getPort();
        }
        String s = lower(uri.getScheme());
        return "https".equals(s) ? 443 : "http".equals(s) ? 80 : -1;
    }

    @NonNull
    private static String lower(@Nullable String value) {
        return value == null ? "" : value.toLowerCase(Locale.ROOT);
    }
}
