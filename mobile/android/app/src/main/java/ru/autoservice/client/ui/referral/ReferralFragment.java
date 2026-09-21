package ru.autoservice.client.ui.referral;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;
import androidx.recyclerview.widget.LinearLayoutManager;

import com.google.android.material.tabs.TabLayout;

import ru.autoservice.client.R;
import ru.autoservice.client.databinding.FragmentReferralBinding;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.common.Ui;
import ru.autoservice.client.util.Formats;
import ru.autoservice.client.util.Qr;

/**
 * Приглашения и баллы.
 *
 * <p>Экран отвечает на три вопроса в том порядке, в котором их задают:
 * сколько у меня накопилось, чем поделиться и что уже произошло. Дерева
 * матрицы здесь нет намеренно — клиенту важно, сколько он заработал и
 * кого привёл, а не кто под кем стоит.
 */
public class ReferralFragment extends Fragment {

    private static final int QR_SIZE_DP = 220;
    private static final int TAB_POINTS = 0;

    private FragmentReferralBinding views;
    private ReferralViewModel model;
    private PointsAdapter pointsAdapter;
    private InvitedAdapter invitedAdapter;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        views = FragmentReferralBinding.inflate(inflater, container, false);
        return views.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        model = new ViewModelProvider(this).get(ReferralViewModel.class);

        pointsAdapter = new PointsAdapter();
        invitedAdapter = new InvitedAdapter();
        views.list.setLayoutManager(new LinearLayoutManager(requireContext()));
        views.list.setAdapter(pointsAdapter);

        views.tabs.addTab(views.tabs.newTab().setText(R.string.referral_tab_points));
        views.tabs.addTab(views.tabs.newTab().setText(R.string.referral_tab_invited));
        views.tabs.addOnTabSelectedListener(new TabLayout.OnTabSelectedListener() {
            @Override
            public void onTabSelected(TabLayout.Tab tab) {
                showTab(tab.getPosition());
            }

            @Override
            public void onTabUnselected(TabLayout.Tab tab) {
            }

            @Override
            public void onTabReselected(TabLayout.Tab tab) {
            }
        });

        views.refresh.setOnRefreshListener(() -> model.load());
        views.share.setOnClickListener(v -> share());
        views.copy.setOnClickListener(v -> copyCode());
        views.attach.setOnClickListener(v -> {
            Ui.hideKeyboard(v);
            model.attach(text());
        });

        observe();
        model.load();
    }

    @Override
    public void onDestroyView() {
        views = null;
        super.onDestroyView();
    }

    private void observe() {
        model.summary().observe(getViewLifecycleOwner(), this::render);

        model.busy().observe(getViewLifecycleOwner(), busy -> {
            if (views != null) {
                views.refresh.setRefreshing(Boolean.TRUE.equals(busy));
            }
        });

        model.points().observe(getViewLifecycleOwner(), entries -> {
            pointsAdapter.submit(entries);
            updateEmpty();
        });

        model.invited().observe(getViewLifecycleOwner(), people -> {
            invitedAdapter.submit(people);
            updateEmpty();
        });

        model.errors().observe(getViewLifecycleOwner(), event -> {
            if (event == null || views == null) {
                return;
            }
            var error = event.consume();
            if (error != null) {
                Ui.showError(views.getRoot(), error);
            }
        });

        model.attached().observe(getViewLifecycleOwner(), event -> {
            if (event != null && event.consume() != null && views != null) {
                views.attachInput.setText("");
                Ui.showMessage(views.getRoot(), R.string.referral_attached);
            }
        });
    }

    private void render(@Nullable Models.Referral referral) {
        if (referral == null || views == null) {
            return;
        }

        Ui.setVisible(views.disabled, !referral.enabled());
        Ui.setVisible(views.content, referral.enabled());
        Ui.setVisible(views.subtitle, referral.enabled());
        if (!referral.enabled()) {
            return;
        }

        views.balance.setText(Formats.money(referral.balance()));
        views.discount.setText(getString(
                R.string.referral_discount, referral.maxDiscountPercent()));
        views.earned.setText(getString(R.string.referral_earned)
                + " " + Formats.money(referral.earnedTotal()));
        views.spent.setText(getString(R.string.referral_spent)
                + " " + Formats.money(referral.spentTotal()));

        views.code.setText(referral.code());
        views.counters.setText(
                getString(R.string.referral_invited_count, referral.invitedCount())
                        + " · " + getString(R.string.referral_team, referral.teamSize()));

        // Ввод чужого кода показываем только пока привязки нет: она
        // одноразовая, и поле, которое всё равно ответит ошибкой, только
        // раздражает.
        Ui.setVisible(views.attachBlock, !referral.attached());

        renderQr(referral.inviteUrl());
    }

    private void renderQr(@NonNull String url) {
        if (views == null || url.isEmpty()) {
            return;
        }
        int size = (int) TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP, QR_SIZE_DP,
                getResources().getDisplayMetrics());
        Bitmap bitmap = Qr.encode(url, size);

        // Не нарисовался — прячем картинку и подпись к ней. Код и кнопка
        // «Поделиться» рядом, экран остаётся рабочим.
        Ui.setVisible(views.qr, bitmap != null);
        Ui.setVisible(views.qrHint, bitmap != null);
        views.qr.setImageBitmap(bitmap);
    }

    private void showTab(int position) {
        if (views == null) {
            return;
        }
        views.list.setAdapter(position == TAB_POINTS ? pointsAdapter : invitedAdapter);
        updateEmpty();
    }

    private void updateEmpty() {
        if (views == null) {
            return;
        }
        boolean points = views.tabs.getSelectedTabPosition() != 1;
        boolean empty = points
                ? pointsAdapter.getItemCount() == 0
                : invitedAdapter.getItemCount() == 0;

        Ui.setVisible(views.empty, empty);
        views.empty.setText(points
                ? R.string.referral_points_empty
                : R.string.referral_invited_empty);
    }

    private void share() {
        Models.Referral referral = model.summary().getValue();
        if (referral == null || referral.inviteUrl().isEmpty()) {
            return;
        }

        String text = getString(R.string.referral_share_text,
                getString(R.string.app_name), referral.code(), referral.inviteUrl());

        Intent intent = new Intent(Intent.ACTION_SEND);
        intent.setType("text/plain");
        intent.putExtra(Intent.EXTRA_SUBJECT,
                getString(R.string.referral_share_subject, getString(R.string.app_name)));
        intent.putExtra(Intent.EXTRA_TEXT, text);
        startActivity(Intent.createChooser(intent, getString(R.string.referral_share)));
    }

    private void copyCode() {
        Models.Referral referral = model.summary().getValue();
        if (referral == null || referral.code().isEmpty() || views == null) {
            return;
        }
        ClipboardManager clipboard =
                (ClipboardManager) requireContext().getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard == null) {
            return;
        }
        clipboard.setPrimaryClip(ClipData.newPlainText(
                getString(R.string.referral_code_label), referral.code()));
        Ui.showMessage(views.getRoot(), R.string.referral_copied);
    }

    @NonNull
    private String text() {
        return views == null || views.attachInput.getText() == null
                ? ""
                : views.attachInput.getText().toString().trim();
    }
}
