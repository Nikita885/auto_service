package ru.autoservice.client.ui.common;

import android.app.Activity;
import android.content.Context;
import android.widget.Toast;

import androidx.activity.result.contract.ActivityResultContract;
import androidx.annotation.NonNull;

import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

import ru.autoservice.client.App;
import ru.autoservice.client.AppContainer;
import ru.autoservice.client.R;
import ru.autoservice.client.data.local.InviteStorage;

/**
 * Приглашение без ручного ввода: код из ссылки, QR или Google Play
 * применяется сам.
 *
 * <p>Новый клиент: код уходит на сервер вместе со входом (AuthRepository),
 * сервер привязывает сразу. Уже вошедший клиент открыл ссылку или
 * отсканировал код — {@link #attachPending} привязывает при старте главного
 * экрана. Отказ «приглашение уже принято» молчит: человек ничего не
 * сломал, просто второй раз открыл ссылку друга.
 */
public final class InviteFlow {

    private InviteFlow() {
    }

    /** Показать итог привязки, случившейся при входе, — один раз. */
    public static void showOutcome(@NonNull Activity activity) {
        InviteStorage.Outcome outcome = App.container(activity).invites().takeOutcome();
        if (outcome == null) {
            return;
        }
        String text = outcome.attached
                ? activity.getString(R.string.invite_attached, outcome.inviterName)
                : outcome.message;
        if (text != null && !text.isEmpty()) {
            Toast.makeText(activity, text, Toast.LENGTH_LONG).show();
        }
    }

    /** Вошедший клиент с отложенным кодом — привязываем без вопросов. */
    public static void attachPending(@NonNull Activity activity) {
        AppContainer container = App.container(activity);
        String code = container.invites().pending();
        if (code == null || !container.auth().isSignedIn()) {
            return;
        }
        Context app = activity.getApplicationContext();
        container.referral().attach(code, result -> {
            container.invites().clear();
            if (result.isSuccess()) {
                Toast.makeText(app, R.string.referral_attached, Toast.LENGTH_LONG).show();
            } else if (result.error() != null && !result.error().is("referral_already_attached")) {
                Toast.makeText(app, Ui.message(app, result.error()), Toast.LENGTH_LONG).show();
            }
        });
    }

    /** Контракт сканера QR: только QR, без писка, с подсказкой. */
    @NonNull
    public static ActivityResultContract<ScanOptions, com.journeyapps.barcodescanner.ScanIntentResult> scanContract() {
        return new ScanContract();
    }

    @NonNull
    public static ScanOptions scanOptions(@NonNull Context context) {
        ScanOptions options = new ScanOptions();
        options.setDesiredBarcodeFormats(ScanOptions.QR_CODE);
        options.setPrompt(context.getString(R.string.scan_prompt));
        options.setBeepEnabled(false);
        options.setOrientationLocked(false);
        return options;
    }
}
