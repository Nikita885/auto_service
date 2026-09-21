package ru.autoservice.client.ui.auth;

import android.content.Intent;
import android.os.Bundle;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.FrameLayout;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.splashscreen.SplashScreen;
import androidx.lifecycle.ViewModelProvider;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.textfield.TextInputEditText;

import ru.autoservice.client.App;
import ru.autoservice.client.BuildConfig;
import ru.autoservice.client.R;
import ru.autoservice.client.data.local.ServerConfig;
import ru.autoservice.client.databinding.ActivityAuthBinding;
import ru.autoservice.client.ui.MainActivity;
import ru.autoservice.client.ui.onboarding.OnboardingActivity;
import ru.autoservice.client.ui.common.SimpleTextWatcher;
import ru.autoservice.client.ui.common.Ui;
import ru.autoservice.client.util.LoginCodeNotice;
import ru.autoservice.client.util.PhoneFormat;

/**
 * Вход по номеру телефона.
 *
 * <p>Стартовый экран приложения: если токен уже есть, пользователь сюда даже
 * не заглядывает — сразу открывается главный экран.
 */
public class AuthActivity extends AppCompatActivity {

    /** Длина кода из SMS — та же, что на сервере (OTP.CODE_LENGTH). */
    private static final int CODE_LENGTH = 4;

    private ActivityAuthBinding views;
    private AuthViewModel model;

    private final ActivityResultLauncher<String> notificationPermission =
            registerForActivityResult(new ActivityResultContracts.RequestPermission(),
                    granted -> { /* отказ ничего не ломает: код виден на экране */ });

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        SplashScreen.installSplashScreen(this);
        super.onCreate(savedInstanceState);

        model = new ViewModelProvider(this).get(AuthViewModel.class);

        // Уже вошли — не показываем форму даже на кадр.
        if (model.isSignedIn()) {
            openMain();
            return;
        }

        views = ActivityAuthBinding.inflate(getLayoutInflater());
        setContentView(views.getRoot());

        askNotificationPermission();
        bindInputs();
        observe();
    }

    private void bindInputs() {
        // Маска ведёт номер: префикс +7 не стирается, цифры группируются.
        PhoneInputFormatter.attach(views.phoneInput, model.phone());
        views.phoneInput.requestFocus();

        // Кнопка активна только когда номер введён целиком: нажатие на неполном
        // номере всё равно вернуло бы ошибку с сервера.
        views.requestCode.setEnabled(PhoneFormat.isComplete(views.phoneInput.getText()));
        views.phoneInput.addTextChangedListener(new SimpleTextWatcher(text ->
                views.requestCode.setEnabled(PhoneFormat.isComplete(text))));

        // Готово на клавиатуре = отправить код, если номер полный.
        views.phoneInput.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_DONE
                    && PhoneFormat.isComplete(views.phoneInput.getText())) {
                views.requestCode.performClick();
                return true;
            }
            return false;
        });

        views.requestCode.setOnClickListener(v -> {
            Ui.hideKeyboard(v);
            model.requestCode(PhoneFormat.toE164(views.phoneInput.getText()));
        });

        views.signIn.setOnClickListener(v -> {
            Ui.hideKeyboard(v);
            model.verifyCode(text(views.codeInput));
        });

        // Код из SMS короткий: как только набран целиком — входим сами,
        // лишнее нажатие тут ни к чему.
        views.codeInput.addTextChangedListener(new SimpleTextWatcher(text -> {
            if (text.length() == CODE_LENGTH) {
                Ui.hideKeyboard(views.codeInput);
                model.verifyCode(text.toString());
            }
        }));

        views.resend.setOnClickListener(v -> model.resend());
        views.changePhone.setOnClickListener(v -> model.editPhone());

        bindServerSettings();
    }

    /**
     * Смена адреса сервера — только в отладочной сборке.
     *
     * <p>Адрес dev-сервера живёт недолго: туннель наружу выдаёт новое имя при
     * каждом перезапуске. Без этого экрана пришлось бы пересобирать APK ради
     * одной строки. В релизе кнопки нет вовсе — адрес там один и зашит.
     */
    private void bindServerSettings() {
        if (!BuildConfig.DEBUG) {
            return;
        }

        ServerConfig config = App.container(this).serverConfig();
        Ui.setVisible(views.serverSettings, true);
        showServer(config);

        views.serverSettings.setOnClickListener(v -> askServer(config));
    }

    private void showServer(@NonNull ServerConfig config) {
        // Схему в подписи не показываем: она занимает половину кнопки.
        String shown = config.baseUrl()
                .replace("https://", "")
                .replace("http://", "");
        views.serverSettings.setText(getString(R.string.server_current, shown));
    }

    private void askServer(@NonNull ServerConfig config) {
        EditText input = new TextInputEditText(this);
        input.setHint(R.string.server_hint);
        input.setText(config.baseUrl());
        input.setSingleLine(true);

        int padding = getResources().getDimensionPixelSize(R.dimen.space);
        FrameLayout wrapper = new FrameLayout(this);
        wrapper.setPadding(padding, padding / 2, padding, 0);
        wrapper.addView(input);

        new MaterialAlertDialogBuilder(this)
                .setTitle(R.string.server_title)
                .setMessage(R.string.server_message)
                .setView(wrapper)
                .setNeutralButton(R.string.server_reset, (dialog, which) -> applyServer(config, ""))
                .setNegativeButton(R.string.action_cancel, null)
                .setPositiveButton(R.string.server_save, (dialog, which) -> applyServer(
                        config, input.getText() == null ? "" : input.getText().toString()))
                .show();
    }

    private void applyServer(@NonNull ServerConfig config, @NonNull String url) {
        config.save(url);
        // Токены выдал прежний сервер — на новом они недействительны.
        App.container(this).onServerChanged();

        showServer(config);
        Ui.showMessage(views.getRoot(), getString(R.string.server_saved, config.baseUrl()));
    }

    private void observe() {
        model.step().observe(this, step -> {
            boolean codeStep = step == AuthViewModel.Step.CODE;
            Ui.setVisible(views.stepPhone, !codeStep);
            Ui.setVisible(views.stepCode, codeStep);

            views.title.setText(codeStep ? R.string.auth_code_title : R.string.auth_title);
            views.subtitle.setText(codeStep
                    ? getString(R.string.auth_code_sub, model.phone())
                    : getString(R.string.auth_sub));

            if (codeStep) {
                views.codeInput.requestFocus();
            }
        });

        model.busy().observe(this, busy -> {
            Ui.setVisible(views.progress, busy);
            // Вернуть кнопку в активное состояние можно только если номер
            // по-прежнему введён целиком — иначе запрос уйдёт с обрывком.
            views.requestCode.setEnabled(!busy
                    && PhoneFormat.isComplete(views.phoneInput.getText()));
            views.signIn.setEnabled(!busy);
        });

        model.resendIn().observe(this, seconds -> {
            boolean waiting = seconds != null && seconds > 0;
            views.resend.setEnabled(!waiting);
            views.resend.setText(waiting
                    ? getString(R.string.auth_resend_in, seconds)
                    : getString(R.string.auth_resend));
        });

        // Код из ответа приходит только с сервера разработки. В релизной
        // сборке поле игнорируем даже если оно каким-то образом пришло:
        // показывать чужой код на экране нельзя.
        model.debugCode().observe(this, code -> {
            boolean show = BuildConfig.DEBUG && code != null && !code.isEmpty();
            Ui.setVisible(views.debugCode, show);
            if (!show) {
                return;
            }
            views.debugCode.setText(getString(R.string.auth_debug_code, code));
            views.codeInput.setText(code);
            // И уведомлением — чтобы код был виден, даже если приложение
            // свернули, пока ждали SMS. Временная заглушка, см.
            // LoginCodeNotice.
            LoginCodeNotice.show(this, code);
        });

        model.errors().observe(this, event -> {
            if (event == null) {
                return;
            }
            var error = event.consume();
            if (error != null) {
                Ui.showError(views.getRoot(), error);
            }
        });

        model.signedIn().observe(this, event -> {
            if (event == null) {
                return;
            }
            var user = event.consume();
            if (user == null) {
                return;
            }
            // Новичка и того, у кого профиль пуст, ведём на знакомство:
            // мастеру у подъёмника нужно знать, кто приехал и на чём, а
            // выяснять это по телефону в день визита — худший способ.
            if (user.isIncomplete()) {
                openOnboarding();
            } else {
                openMain();
            }
        });
    }

    private void openOnboarding() {
        Intent intent = new Intent(this, OnboardingActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(intent);
        finish();
    }

    /**
     * Разрешение на уведомления — только ради временной заглушки с кодом
     * входа (см. {@link LoginCodeNotice}). Отказ ничего не ломает: код
     * виден прямо на экране, уведомление здесь удобство, а не механизм.
     */
    private void askNotificationPermission() {
        if (!LoginCodeNotice.needsPermission(this)) {
            return;
        }
        notificationPermission.launch(android.Manifest.permission.POST_NOTIFICATIONS);
    }

    private void openMain() {
        Intent intent = new Intent(this, MainActivity.class);
        // Экран входа из стека убираем: кнопка «назад» не должна возвращать
        // к форме, из которой уже вошли.
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(intent);
        finish();
    }

    @NonNull
    private static String text(@NonNull android.widget.EditText input) {
        return input.getText() == null ? "" : input.getText().toString();
    }
}
