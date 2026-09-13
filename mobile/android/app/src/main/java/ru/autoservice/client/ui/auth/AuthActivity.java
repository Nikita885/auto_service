package ru.autoservice.client.ui.auth;

import android.content.Intent;
import android.os.Bundle;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.splashscreen.SplashScreen;
import androidx.lifecycle.ViewModelProvider;

import ru.autoservice.client.BuildConfig;
import ru.autoservice.client.R;
import ru.autoservice.client.databinding.ActivityAuthBinding;
import ru.autoservice.client.ui.MainActivity;
import ru.autoservice.client.ui.common.Ui;

/**
 * Вход по номеру телефона.
 *
 * <p>Стартовый экран приложения: если токен уже есть, пользователь сюда даже
 * не заглядывает — сразу открывается главный экран.
 */
public class AuthActivity extends AppCompatActivity {

    private ActivityAuthBinding views;
    private AuthViewModel model;

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

        bindInputs();
        observe();
    }

    private void bindInputs() {
        views.phoneInput.setText(model.phone());

        views.requestCode.setOnClickListener(v -> {
            Ui.hideKeyboard(v);
            model.requestCode(text(views.phoneInput));
        });

        views.signIn.setOnClickListener(v -> {
            Ui.hideKeyboard(v);
            model.verifyCode(text(views.codeInput));
        });

        views.resend.setOnClickListener(v -> model.resend());
        views.changePhone.setOnClickListener(v -> model.editPhone());
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
            views.requestCode.setEnabled(!busy);
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
            if (show) {
                views.debugCode.setText(getString(R.string.auth_debug_code, code));
                views.codeInput.setText(code);
            }
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
            if (event != null && event.consume() != null) {
                openMain();
            }
        });
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
