package ru.autoservice.client.ui.onboarding;

import android.content.Intent;
import android.os.Bundle;
import android.widget.EditText;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.lifecycle.ViewModelProvider;

import ru.autoservice.client.R;
import ru.autoservice.client.databinding.ActivityOnboardingBinding;
import ru.autoservice.client.ui.MainActivity;
import ru.autoservice.client.ui.cars.CarPickerDialog;
import ru.autoservice.client.ui.common.Ui;

/**
 * Знакомство после первого входа: имя, автомобиль, госномер и код
 * приглашения.
 *
 * <p>Отдельный экран, а не «загляните в профиль»: мастеру у подъёмника
 * нужно знать, кто приехал и на чём, и узнавать это по телефону в день
 * визита — худший из способов. Пропустить всё равно можно: заставлять
 * заполнять анкету сразу после входа — верный способ потерять человека.
 */
public class OnboardingActivity extends AppCompatActivity {

    private ActivityOnboardingBinding views;
    private OnboardingViewModel model;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        views = ActivityOnboardingBinding.inflate(getLayoutInflater());
        setContentView(views.getRoot());

        model = new ViewModelProvider(this).get(OnboardingViewModel.class);

        if (savedInstanceState == null) {
            // Пришёл по ссылке-приглашению — код уже известен, набирать
            // его руками не нужно.
            views.inviteInput.setText(model.pendingInvite());
        }

        views.car.setOnClickListener(v -> CarPickerDialog.show(getSupportFragmentManager()));
        getSupportFragmentManager().setFragmentResultListener(
                CarPickerDialog.RESULT, this,
                (key, bundle) -> model.setCar(bundle.getString(CarPickerDialog.KEY_TITLE, "")));

        views.done.setOnClickListener(v -> {
            Ui.hideKeyboard(v);
            if (text(views.nameInput).isEmpty()) {
                // Без имени запись для мастера выглядит как «клиент» —
                // именно поэтому имя здесь и спрашивают.
                Ui.showMessage(views.getRoot(), R.string.onboarding_name_required);
                return;
            }
            model.save(text(views.nameInput), text(views.plateInput), text(views.inviteInput));
        });

        views.skip.setOnClickListener(v -> model.skip());

        observe();
    }

    private void observe() {
        model.car().observe(this, title -> {
            boolean chosen = title != null && !title.isEmpty();
            views.car.setText(chosen ? title : getString(R.string.onboarding_car_empty));
        });

        model.busy().observe(this, busy -> {
            boolean working = Boolean.TRUE.equals(busy);
            views.done.setEnabled(!working);
            views.skip.setEnabled(!working);
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

        model.inviteFailed().observe(this, event -> {
            if (event != null && event.consume() != null) {
                Ui.showMessage(views.getRoot(), R.string.onboarding_invite_failed);
            }
        });

        model.done().observe(this, event -> {
            if (event != null && event.consume() != null) {
                openMain();
            }
        });
    }

    private void openMain() {
        Intent intent = new Intent(this, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(intent);
        finish();
    }

    @NonNull
    private static String text(@NonNull EditText input) {
        return input.getText() == null ? "" : input.getText().toString().trim();
    }
}
