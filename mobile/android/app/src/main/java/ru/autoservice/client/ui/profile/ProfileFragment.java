package ru.autoservice.client.ui.profile;

import android.content.Intent;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;

import ru.autoservice.client.BuildConfig;
import ru.autoservice.client.R;
import ru.autoservice.client.databinding.FragmentProfileBinding;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.auth.AuthActivity;
import ru.autoservice.client.ui.common.Ui;

/** Профиль: имя и автомобиль для мастера, выход из аккаунта. */
public class ProfileFragment extends Fragment {

    private FragmentProfileBinding views;
    private ProfileViewModel model;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        views = FragmentProfileBinding.inflate(inflater, container, false);
        return views.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        model = new ViewModelProvider(this).get(ProfileViewModel.class);

        views.version.setText(getString(R.string.profile_version, BuildConfig.VERSION_NAME));

        views.save.setOnClickListener(v -> {
            Ui.hideKeyboard(v);
            model.save(
                    text(views.nameInput),
                    text(views.carInput),
                    text(views.plateInput));
        });

        views.signOut.setOnClickListener(v -> Ui.confirm(
                requireContext(),
                getString(R.string.profile_sign_out_title),
                getString(R.string.profile_sign_out_message),
                R.string.profile_sign_out,
                () -> model.signOut()));

        observe();
        model.load();
    }

    @Override
    public void onDestroyView() {
        views = null;
        super.onDestroyView();
    }

    private void observe() {
        model.user().observe(getViewLifecycleOwner(), this::render);

        model.busy().observe(getViewLifecycleOwner(),
                busy -> views.save.setEnabled(!Boolean.TRUE.equals(busy)));

        model.errors().observe(getViewLifecycleOwner(), event -> {
            if (event == null) {
                return;
            }
            var error = event.consume();
            if (error != null && views != null) {
                Ui.showError(views.getRoot(), error);
            }
        });

        model.saved().observe(getViewLifecycleOwner(), event -> {
            if (event != null && event.consume() != null && views != null) {
                Ui.showMessage(views.getRoot(), R.string.profile_saved);
            }
        });

        model.signedOut().observe(getViewLifecycleOwner(), event -> {
            if (event != null && event.consume() != null) {
                openAuth();
            }
        });
    }

    private void render(@Nullable Models.User user) {
        if (user == null || views == null) {
            return;
        }
        views.phone.setText(user.phone());

        // Поля заполняем только когда они пустые: иначе ответ сервера затрёт
        // то, что человек печатает прямо сейчас.
        if (text(views.nameInput).isEmpty()) {
            views.nameInput.setText(user.fullName());
        }
        if (text(views.carInput).isEmpty()) {
            views.carInput.setText(user.carModel());
        }
        if (text(views.plateInput).isEmpty()) {
            views.plateInput.setText(user.carPlate());
        }
    }

    private void openAuth() {
        Intent intent = new Intent(requireContext(), AuthActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(intent);
        requireActivity().finish();
    }

    @NonNull
    private static String text(@NonNull android.widget.EditText input) {
        return input.getText() == null ? "" : input.getText().toString().trim();
    }
}
