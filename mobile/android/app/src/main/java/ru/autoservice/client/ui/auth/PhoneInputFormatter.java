package ru.autoservice.client.ui.auth;

import android.text.Editable;
import android.text.TextWatcher;
import android.widget.EditText;

import androidx.annotation.NonNull;

import ru.autoservice.client.util.PhoneFormat;

/**
 * Маска номера на поле ввода.
 *
 * <p>Здесь только работа с полем: разбор и сборка строки живут в
 * {@link PhoneFormat}, который тестируется обычными JUnit-тестами.
 *
 * <p>Своя маска, а не системный {@code PhoneNumberFormattingTextWatcher}: тот
 * форматирует по локали устройства, и на телефоне с другой локалью номер
 * выглядел бы иначе, чем на сайте.
 */
public final class PhoneInputFormatter implements TextWatcher {

    private final EditText input;
    private boolean selfChange;

    private PhoneInputFormatter(@NonNull EditText input) {
        this.input = input;
    }

    /** Повесить маску на поле и подставить начальный номер. */
    public static void attach(@NonNull EditText input, @NonNull String initialPhone) {
        input.addTextChangedListener(new PhoneInputFormatter(input));

        String formatted = PhoneFormat.format(PhoneFormat.digitsOf(initialPhone));
        input.setText(formatted);
        input.setSelection(formatted.length());
    }

    @Override
    public void afterTextChanged(Editable editable) {
        // Свою же правку повторно не форматируем, иначе получится рекурсия.
        if (selfChange) {
            return;
        }

        String digits = PhoneFormat.digitsOf(editable);
        String formatted = PhoneFormat.format(digits);
        if (formatted.contentEquals(editable)) {
            return;
        }

        int cursor = PhoneFormat.cursorAfterDigits(formatted, digits.length());

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
}
