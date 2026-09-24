package ru.autoservice.client.util;

import androidx.annotation.Nullable;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Код приглашения из того, что пришло снаружи: из QR, из ссылки, из
 * параметра установки Google Play.
 *
 * <p>В QR лежит ссылка `https://<сайт>/i/<код>`; голый код тоже принимаем.
 * Любой другой QR — чужой сайт, Wi-Fi — не приглашение, и подставлять из
 * него «что-то похожее» нельзя: человек привязался бы к случайному коду.
 * Правила те же, что у веб-приложения (static/web/app/scan.js).
 */
public final class InviteCodes {

    private static final Pattern LINK = Pattern.compile("/i/([A-Za-z0-9]{4,10})/?(?:[?#].*)?$");
    private static final Pattern QUERY = Pattern.compile("[?&]invite=([A-Za-z0-9]{4,10})");
    private static final Pattern RAW = Pattern.compile("^[A-Za-z0-9]{4,10}$");
    private static final Pattern REFERRER = Pattern.compile("(?:^|&)invite=([A-Za-z0-9]{4,10})(?:&|$)");

    private InviteCodes() {
    }

    /** Код из прочитанного QR или ссылки; null — это не приглашение. */
    @Nullable
    public static String parse(@Nullable String text) {
        if (text == null) {
            return null;
        }
        String raw = text.trim();
        Matcher link = LINK.matcher(raw);
        if (link.find()) {
            return upper(link.group(1));
        }
        Matcher query = QUERY.matcher(raw);
        if (query.find()) {
            return upper(query.group(1));
        }
        return RAW.matcher(raw).matches() ? upper(raw) : null;
    }

    /**
     * Код из параметра установки Google Play: сайт кладёт в ссылку на магазин
     * `referrer=invite=<код>`, а Play отдаёт его приложению после установки.
     */
    @Nullable
    public static String fromReferrer(@Nullable String referrer) {
        if (referrer == null) {
            return null;
        }
        Matcher m = REFERRER.matcher(referrer.trim());
        return m.find() ? upper(m.group(1)) : null;
    }

    private static String upper(String value) {
        return value.toUpperCase(Locale.ROOT);
    }
}
