package ru.autoservice.client.ui.common;

import android.text.Editable;
import android.text.TextWatcher;

import androidx.annotation.NonNull;

/**
 * {@link TextWatcher}, из которого нужен только результат ввода.
 *
 * <p>Штатный интерфейс требует три метода, из которых обычно интересен один.
 * Обёртка убирает два пустых переопределения на каждом поле ввода.
 *
 * <p>Лежит в общем пакете, а не рядом с экраном входа: поля ввода есть и
 * в профиле, и в выборе автомобиля, а вторая копия того же класса рано или
 * поздно начинает отличаться от первой.
 */
public final class SimpleTextWatcher implements TextWatcher {

    public interface OnChanged {
        void onChanged(@NonNull CharSequence text);
    }

    private final OnChanged listener;

    public SimpleTextWatcher(@NonNull OnChanged listener) {
        this.listener = listener;
    }

    @Override
    public void afterTextChanged(Editable editable) {
        listener.onChanged(editable == null ? "" : editable);
    }

    @Override
    public void beforeTextChanged(CharSequence s, int start, int count, int after) {
    }

    @Override
    public void onTextChanged(CharSequence s, int start, int before, int count) {
    }
}
