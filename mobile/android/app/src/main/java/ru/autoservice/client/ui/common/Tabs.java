package ru.autoservice.client.ui.common;

import androidx.annotation.IdRes;
import androidx.annotation.NonNull;
import androidx.fragment.app.Fragment;
import androidx.fragment.app.FragmentManager;
import androidx.fragment.app.FragmentTransaction;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Вкладки нижнего меню: все фрагменты живут одновременно, виден один.
 *
 * <p>Вынесено из {@code MainActivity} ради одной ошибки, которую легко
 * повторить. {@code commit()} асинхронный: фрагменты, добавленные отдельными
 * транзакциями, ещё не найдутся через {@code findFragmentByTag} в том же
 * кадре. Раньше старт делал четыре {@code add().hide().commit()} и сразу
 * {@code show(первая)} — поиск ничего не находил, все вкладки оставались
 * скрытыми, и «Запись» была пустой, пока не переключишься туда и обратно.
 * Здесь добавление и выбор первой вкладки — одна транзакция, искать по
 * тегу до её выполнения нечего.
 */
public final class Tabs {

    private Tabs() {
    }

    /**
     * Холодный старт: добавить все вкладки, показать {@code selected}.
     *
     * @param tabs тег → фрагмент, в порядке меню
     */
    public static void setUp(@NonNull FragmentManager manager, @IdRes int container,
                             @NonNull LinkedHashMap<String, Fragment> tabs,
                             @NonNull String selected) {
        FragmentTransaction transaction = manager.beginTransaction();
        for (Map.Entry<String, Fragment> tab : tabs.entrySet()) {
            transaction.add(container, tab.getValue(), tab.getKey());
            if (!tab.getKey().equals(selected)) {
                transaction.hide(tab.getValue());
            }
        }
        transaction.commit();
    }

    /** Переключение: показать {@code selected}, остальные спрятать. */
    public static void show(@NonNull FragmentManager manager, @NonNull String[] tags,
                            @NonNull String selected) {
        // Переключение приходит по нажатию, когда стартовая транзакция давно
        // выполнена. Но если нажать успели в первом же кадре — доводим её,
        // иначе поиск по тегу снова ничего не найдёт.
        manager.executePendingTransactions();
        FragmentTransaction transaction = manager.beginTransaction();
        for (String tag : tags) {
            Fragment fragment = manager.findFragmentByTag(tag);
            if (fragment == null) {
                continue;
            }
            if (tag.equals(selected)) {
                transaction.show(fragment);
            } else {
                transaction.hide(fragment);
            }
        }
        transaction.commit();
    }
}
