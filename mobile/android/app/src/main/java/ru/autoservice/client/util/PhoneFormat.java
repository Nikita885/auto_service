package ru.autoservice.client.util;

import androidx.annotation.NonNull;

/**
 * Разбор и форматирование российского номера: {@code +7 (900) 111-22-33}.
 *
 * <p>Чистая логика без единой ссылки на Android — её можно прогнать обычными
 * JUnit-тестами, что для маски ввода важнее, чем для чего-либо ещё: ошибка
 * здесь видна не в падении, а в том, что у человека «не удаляется семёрка».
 *
 * <p>Ключевое правило: поле ввода <b>всегда</b> начинается с {@code +7}, и эти
 * два символа — код страны, а не часть номера. Всё, что после них, —
 * национальные цифры.
 */
public final class PhoneFormat {

    /** Код страны, который всегда стоит в поле. */
    public static final String PREFIX = "+7";

    /** Сколько цифр в номере после кода страны. */
    public static final int NATIONAL_DIGITS = 10;

    private PhoneFormat() {
    }

    /**
     * Национальные цифры из содержимого поля.
     *
     * <p>Сначала снимается собственный префикс поля — иначе его «7» станет
     * первой цифрой номера, и человек увидит, что семёрка не стирается.
     * Затем разбирается то, что осталось: вставленные {@code 8 900…},
     * {@code +7 900…} и {@code 9001112233} должны дать одни и те же цифры,
     * иначе один человек заведёт три аккаунта.
     */
    @NonNull
    public static String digitsOf(@NonNull CharSequence text) {
        String value = text.toString();
        if (value.startsWith(PREFIX)) {
            value = value.substring(PREFIX.length());
        }

        StringBuilder digits = new StringBuilder();
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (Character.isDigit(c)) {
                digits.append(c);
            }
        }

        String national = digits.toString();

        // Одиннадцать цифр с ведущей 7 или 8 — это номер с кодом страны,
        // который вставили целиком.
        if (national.length() == NATIONAL_DIGITS + 1
                && (national.charAt(0) == '7' || national.charAt(0) == '8')) {
            national = national.substring(1);
        }

        return national.length() > NATIONAL_DIGITS
                ? national.substring(0, NATIONAL_DIGITS)
                : national;
    }

    /** Цифры в маску. Пустой номер — это просто префикс, поле не бывает пустым. */
    @NonNull
    public static String format(@NonNull String digits) {
        StringBuilder out = new StringBuilder(PREFIX);
        if (digits.isEmpty()) {
            return out.toString();
        }

        out.append(" (").append(digits, 0, Math.min(3, digits.length()));
        if (digits.length() >= 3) {
            out.append(")");
        }
        if (digits.length() > 3) {
            out.append(" ").append(digits, 3, Math.min(6, digits.length()));
        }
        if (digits.length() > 6) {
            out.append("-").append(digits, 6, Math.min(8, digits.length()));
        }
        if (digits.length() > 8) {
            out.append("-").append(digits, 8, digits.length());
        }
        return out.toString();
    }

    /** Номер в виде, который ждёт сервер: {@code +79001112233}. */
    @NonNull
    public static String toE164(@NonNull CharSequence text) {
        String digits = digitsOf(text);
        return digits.isEmpty() ? "" : PREFIX + digits;
    }

    /** Введён ли номер целиком. По этому включается кнопка. */
    public static boolean isComplete(@NonNull CharSequence text) {
        return digitsOf(text).length() == NATIONAL_DIGITS;
    }

    /**
     * Куда поставить курсор после переформатирования.
     *
     * <p>Сразу за последней введённой цифрой, а не в конец строки: иначе он
     * уходил бы за закрывающую скобку, и следующая цифра попадала не туда.
     */
    public static int cursorAfterDigits(@NonNull String formatted, int digitCount) {
        if (digitCount <= 0) {
            return formatted.length();
        }
        int seen = 0;
        // Первые символы — префикс «+7», его цифру не считаем.
        for (int i = PREFIX.length(); i < formatted.length(); i++) {
            if (Character.isDigit(formatted.charAt(i))) {
                seen++;
                if (seen == digitCount) {
                    return i + 1;
                }
            }
        }
        return formatted.length();
    }
}
