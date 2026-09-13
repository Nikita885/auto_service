package ru.autoservice.client.ui.auth;

import android.text.Editable;
import android.text.TextWatcher;
import android.widget.EditText;

import androidx.annotation.NonNull;

/**
 * Маска российского номера: {@code +7 (900) 111-22-33}.
 *
 * <p>Зачем своя, а не системный {@code PhoneNumberFormattingTextWatcher}: тот
 * форматирует по локали устройства, и на телефоне с другой локалью номер
 * выглядит иначе. Здесь формат один и тот же у всех, и он совпадает с тем,
 * что клиент видит на сайте.
 *
 * <p>Правила:
 * <ul>
 *   <li>префикс {@code +7} стоит всегда и не удаляется — стирая номер,
 *       человек не остаётся с пустым полем, в котором непонятно, что вводить;
 *   <li>вставка из буфера разбирается как есть: {@code 8 900…},
 *       {@code +7 900…} и {@code 79001112233} дают один и тот же номер;
 *   <li>лишние цифры сверх десяти отбрасываются.
 * </ul>
 *
 * <p>Сервер всё равно нормализует телефон сам — маска нужна не ему, а человеку:
 * набирая вслепую, легко пропустить цифру, а сгруппированный номер видно.
 */
public final class PhoneInputFormatter implements TextWatcher {

    /** Сколько цифр в номере после кода страны. */
    private static final int NATIONAL_DIGITS = 10;

    private final EditText input;
    private boolean selfChange;

    private PhoneInputFormatter(@NonNull EditText input) {
        this.input = input;
    }

    /** Повесить маску на поле и подставить в него начальный номер. */
    public static void attach(@NonNull EditText input, @NonNull String initialPhone) {
        PhoneInputFormatter formatter = new PhoneInputFormatter(input);
        input.addTextChangedListener(formatter);

        String digits = nationalDigits(initialPhone);
        String formatted = format(digits);
        input.setText(formatted);
        input.setSelection(formatted.length());
    }

    /** Номер в виде, который ждёт сервер: {@code +79001112233}. */
    @NonNull
    public static String toE164(@NonNull CharSequence text) {
        String digits = nationalDigits(text.toString());
        return digits.isEmpty() ? "" : "+7" + digits;
    }

    /** Введён ли номер целиком. По нему включается кнопка. */
    public static boolean isComplete(@NonNull CharSequence text) {
        return nationalDigits(text.toString()).length() == NATIONAL_DIGITS;
    }

    @Override
    public void afterTextChanged(Editable editable) {
        if (selfChange) {
            return;
        }

        String digits = nationalDigits(editable.toString());
        String formatted = format(digits);
        if (formatted.contentEquals(editable)) {
            return;
        }

        // Курсор ставим в конец введённых цифр, а не в конец строки: иначе он
        // прыгал бы за скобку и следующая цифра уходила не туда.
        int cursor = cursorAfterDigits(formatted, digits.length());

        selfChange = true;
        editable.replace(0, editable.length(), formatted);
        selfChange = false;

        input.setSelection(Math.min(cursor, formatted.length()));
    }

    @Override
    public void beforeTextChanged(CharSequence s, int start, int count, int after) {
    }

    @Override
    public void onTextChanged(CharSequence s, int start, int before, int count) {
    }

    /* ------------------------------------------------------------ разбор */

    /**
     * Десять цифр национального номера из любого написания.
     *
     * <p>Ведущие 7 и 8 — это код страны, а не часть номера: «8 900 111-22-33»
     * и «+7 900 111-22-33» должны дать одни и те же цифры, иначе один человек
     * заведёт два аккаунта.
     */
    @NonNull
    private static String nationalDigits(@NonNull String raw) {
        StringBuilder digits = new StringBuilder();
        for (int i = 0; i < raw.length(); i++) {
            char c = raw.charAt(i);
            if (Character.isDigit(c)) {
                digits.append(c);
            }
        }

        String value = digits.toString();
        if (value.startsWith("7") || value.startsWith("8")) {
            // Отрезаем код страны только если за ним есть похожий на номер остаток.
            if (value.length() > NATIONAL_DIGITS) {
                value = value.substring(1);
            }
        }
        return value.length() > NATIONAL_DIGITS ? value.substring(0, NATIONAL_DIGITS) : value;
    }

    /** Цифры в маску: {@code +7 (900) 111-22-33}. */
    @NonNull
    private static String format(@NonNull String digits) {
        StringBuilder out = new StringBuilder("+7");
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

    /** Позиция сразу после последней введённой цифры. */
    private static int cursorAfterDigits(@NonNull String formatted, int digitCount) {
        if (digitCount == 0) {
            return formatted.length();
        }
        int seen = 0;
        // Первые две цифры строки — код страны «+7», их не считаем.
        for (int i = 2; i < formatted.length(); i++) {
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
