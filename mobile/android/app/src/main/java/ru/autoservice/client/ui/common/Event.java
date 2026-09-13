package ru.autoservice.client.ui.common;

import androidx.annotation.Nullable;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

/**
 * Одноразовое событие для LiveData.
 *
 * <p>Обычная LiveData повторяет последнее значение новому наблюдателю. Для
 * состояния это правильно, а для «показать ошибку» — нет: после поворота
 * экрана пользователь снова увидел бы снекбар о том, что уже прочитал.
 */
public final class Event<T> {

    @Nullable private final T content;
    private boolean handled;

    public Event(@Nullable T content) {
        this.content = content;
    }

    /** Отдаёт содержимое ровно один раз. Повторный вызов вернёт null. */
    @Nullable
    public T consume() {
        if (handled) {
            return null;
        }
        handled = true;
        return content;
    }

    /** LiveData одноразовых событий с удобным методом публикации. */
    public static final class Bus<T> extends MutableLiveData<Event<T>> {

        public void post(@Nullable T value) {
            setValue(new Event<>(value));
        }

        public LiveData<Event<T>> asLiveData() {
            return this;
        }
    }
}
