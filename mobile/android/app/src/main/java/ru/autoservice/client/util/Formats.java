package ru.autoservice.client.util;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.text.NumberFormat;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/**
 * Форматирование дат, денег и телефонов.
 *
 * <p>Сервер отдаёт время в UTC (ISO-8601), а показывать его нужно так, как
 * думает человек. Для времени визита используется часовой пояс точки — он
 * приходит в её карточке: адрес в другом регионе не должен показывать
 * клиенту время его собственного телефона.
 */
public final class Formats {

    private static final Locale RU = new Locale("ru", "RU");

    private Formats() {
    }

    /** Разбор ISO-8601 c сервера: {@code 2026-09-11T16:00:00Z} или со смещением. */
    @Nullable
    public static Date parseIso(@Nullable String iso) {
        if (iso == null || iso.isEmpty()) {
            return null;
        }
        // Нормализуем «Z» и «+03:00» к виду, который понимает SimpleDateFormat.
        String normalized = iso.replace("Z", "+0000");
        int lastColon = normalized.lastIndexOf(':');
        if (lastColon > 10 && (normalized.length() - lastColon) == 3
                && (normalized.charAt(lastColon - 3) == '+' || normalized.charAt(lastColon - 3) == '-')) {
            normalized = normalized.substring(0, lastColon) + normalized.substring(lastColon + 1);
        }
        String pattern = normalized.contains(".")
                ? "yyyy-MM-dd'T'HH:mm:ss.SSSZ"
                : "yyyy-MM-dd'T'HH:mm:ssZ";
        try {
            return new SimpleDateFormat(pattern, RU).parse(normalized);
        } catch (ParseException e) {
            return null;
        }
    }

    /** Дата в формате, который ждёт сервер в параметре {@code ?date=}. */
    @NonNull
    public static String isoDate(@NonNull Date date, @NonNull TimeZone zone) {
        return format(date, "yyyy-MM-dd", zone);
    }

    /** «11 сентября, 19:00» — для карточки записи. */
    @NonNull
    public static String dateTime(@NonNull Date date, @NonNull TimeZone zone) {
        return format(date, "d MMMM, HH:mm", zone);
    }

    /** «11 сентября» */
    @NonNull
    public static String dateLong(@NonNull Date date, @NonNull TimeZone zone) {
        return format(date, "d MMMM", zone);
    }

    /** «пн, 11 сен» — подпись дня в выборе времени. */
    @NonNull
    public static String dayChip(@NonNull Date date, @NonNull TimeZone zone) {
        return format(date, "EE, d MMM", zone);
    }

    /** «19:00» */
    @NonNull
    public static String time(@NonNull Date date, @NonNull TimeZone zone) {
        return format(date, "HH:mm", zone);
    }

    private static String format(@NonNull Date date, @NonNull String pattern, @NonNull TimeZone zone) {
        SimpleDateFormat formatter = new SimpleDateFormat(pattern, RU);
        formatter.setTimeZone(zone);
        return formatter.format(date);
    }

    @NonNull
    public static TimeZone zoneOrDefault(@Nullable String id) {
        return id == null || id.isEmpty() ? TimeZone.getDefault() : TimeZone.getTimeZone(id);
    }

    /** «3 600 ₽». Копейки не показываем: цены в прайсе всегда целые. */
    @NonNull
    public static String money(double amount) {
        NumberFormat format = NumberFormat.getIntegerInstance(RU);
        return format.format(Math.round(amount)) + " ₽";
    }

    /** «04:38» — таймер черновика. */
    @NonNull
    public static String clock(int seconds) {
        int safe = Math.max(seconds, 0);
        return String.format(RU, "%02d:%02d", safe / 60, safe % 60);
    }

    /**
     * Приведение телефона к E.164 — тому же виду, что хранит сервер.
     *
     * <p>«8 900 111-22-33», «+7 900 111 22 33» и «79001112233» — один и тот же
     * человек. Если не нормализовать, он заведёт три аккаунта.
     */
    @NonNull
    public static String normalizePhone(@NonNull String raw) {
        StringBuilder digits = new StringBuilder();
        for (char c : raw.toCharArray()) {
            if (Character.isDigit(c)) {
                digits.append(c);
            }
        }
        String value = digits.toString();
        if (value.length() == 11 && value.charAt(0) == '8') {
            value = "7" + value.substring(1);
        }
        if (value.length() == 10) {
            value = "7" + value;
        }
        return value.isEmpty() ? raw.trim() : "+" + value;
    }

    /** Склонение: 1 канистра, 2 канистры, 5 канистр. */
    @NonNull
    public static String plural(int count, @NonNull String one, @NonNull String few, @NonNull String many) {
        int mod100 = Math.abs(count) % 100;
        int mod10 = mod100 % 10;
        if (mod100 > 10 && mod100 < 20) {
            return many;
        }
        if (mod10 > 1 && mod10 < 5) {
            return few;
        }
        return mod10 == 1 ? one : many;
    }
}
