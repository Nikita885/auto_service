package ru.autoservice.client.ui.common;

import android.content.Context;
import android.view.View;
import android.view.inputmethod.InputMethodManager;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.annotation.StringRes;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.snackbar.Snackbar;

import ru.autoservice.client.R;
import ru.autoservice.client.util.ApiError;

/**
 * Мелкие вещи, которые иначе расползаются по экранам:
 * показ ошибки, подтверждение действия, скрытие клавиатуры.
 */
public final class Ui {

    private Ui() {
    }

    /**
     * Человеческий текст ошибки.
     *
     * <p>Сообщение сервера показываем как есть — оно написано для клиента и
     * правится без релиза приложения. Свои формулировки нужны только там, где
     * сервер ничего сказать не мог: нет сети или ответ не разобрался.
     */
    @NonNull
    public static String message(@NonNull Context context, @NonNull ApiError error) {
        if (error.is(ApiError.CODE_NETWORK)) {
            return context.getString(R.string.error_network);
        }
        if (!error.message().isEmpty()) {
            return error.message();
        }
        return context.getString(R.string.error_unknown);
    }

    public static void showError(@NonNull View anchor, @NonNull ApiError error) {
        Snackbar.make(anchor, message(anchor.getContext(), error), Snackbar.LENGTH_LONG).show();
    }

    public static void showMessage(@NonNull View anchor, @NonNull String text) {
        Snackbar.make(anchor, text, Snackbar.LENGTH_LONG).show();
    }

    public static void showMessage(@NonNull View anchor, @StringRes int text) {
        Snackbar.make(anchor, text, Snackbar.LENGTH_LONG).show();
    }

    /** Подтверждение необратимого действия: отмены записи, выхода из аккаунта. */
    public static void confirm(@NonNull Context context,
                               @NonNull String title,
                               @Nullable String message,
                               @StringRes int positive,
                               @NonNull Runnable onConfirmed) {
        new MaterialAlertDialogBuilder(context)
                .setTitle(title)
                .setMessage(message)
                .setNegativeButton(R.string.action_cancel, null)
                .setPositiveButton(positive, (dialog, which) -> onConfirmed.run())
                .show();
    }

    public static void hideKeyboard(@NonNull View view) {
        InputMethodManager manager =
                (InputMethodManager) view.getContext().getSystemService(Context.INPUT_METHOD_SERVICE);
        if (manager != null) {
            manager.hideSoftInputFromWindow(view.getWindowToken(), 0);
        }
    }

    public static void setVisible(@NonNull View view, boolean visible) {
        view.setVisibility(visible ? View.VISIBLE : View.GONE);
    }
}
