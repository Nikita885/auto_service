package ru.autoservice.client.ui.bookings;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;

import com.google.android.material.dialog.MaterialAlertDialogBuilder;
import com.google.android.material.textfield.TextInputEditText;

import java.util.List;

import ru.autoservice.client.R;
import ru.autoservice.client.data.repository.BookingRepository;
import ru.autoservice.client.databinding.FragmentBookingsBinding;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.common.Ui;

/** Мои записи: предстоящие и история. */
public class BookingsFragment extends Fragment {

    private FragmentBookingsBinding views;
    private BookingsViewModel model;
    private BookingAdapter adapter;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        views = FragmentBookingsBinding.inflate(inflater, container, false);
        return views.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        model = new ViewModelProvider(this).get(BookingsViewModel.class);

        adapter = new BookingAdapter(this::askCancel);
        views.list.setAdapter(adapter);

        views.scopeGroup.check(R.id.scope_upcoming);
        views.scopeGroup.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (!isChecked) {
                return;
            }
            model.setScope(checkedId == R.id.scope_upcoming
                    ? BookingRepository.SCOPE_UPCOMING
                    : BookingRepository.SCOPE_HISTORY);
        });

        views.refresh.setOnRefreshListener(() -> model.refresh());

        observe();
    }

    @Override
    public void onStart() {
        super.onStart();
        if (!isHidden()) {
            model.refresh();
        }
    }

    @Override
    public void onHiddenChanged(boolean hidden) {
        super.onHiddenChanged(hidden);
        // Перечитываем при показе: запись могли отменить из панели мастера,
        // пока вкладка была скрыта.
        if (!hidden) {
            model.refresh();
        }
    }

    @Override
    public void onDestroyView() {
        views.list.setAdapter(null);
        views = null;
        super.onDestroyView();
    }

    /** Обновление снаружи: например, после создания записи на соседней вкладке. */
    public void reload() {
        if (model != null) {
            model.refresh();
        }
    }

    private void observe() {
        model.items().observe(getViewLifecycleOwner(), this::render);

        model.loading().observe(getViewLifecycleOwner(),
                loading -> views.refresh.setRefreshing(Boolean.TRUE.equals(loading)));

        model.errors().observe(getViewLifecycleOwner(), event -> {
            if (event == null) {
                return;
            }
            var error = event.consume();
            if (error != null && views != null) {
                Ui.showError(views.getRoot(), error);
            }
        });

        model.cancelled().observe(getViewLifecycleOwner(), event -> {
            if (event != null && event.consume() != null && views != null) {
                Ui.showMessage(views.getRoot(), R.string.booking_cancelled);
            }
        });
    }

    private void render(@Nullable List<Models.Booking> items) {
        if (views == null) {
            return;
        }
        adapter.submitList(items);

        boolean empty = items == null || items.isEmpty();
        Ui.setVisible(views.empty, empty);
        views.empty.setText(model.isUpcoming()
                ? R.string.bookings_empty_upcoming
                : R.string.bookings_empty_history);
    }

    /**
     * Отмена с необязательной причиной.
     *
     * <p>Причину не требуем: клиент не обязан объясняться. Сервису она полезна,
     * но не ценой того, что человек не сможет отменить запись.
     */
    private void askCancel(@NonNull Models.Booking booking) {
        EditText input = new TextInputEditText(requireContext());
        input.setHint(R.string.booking_cancel_reason_hint);
        input.setMaxLines(2);

        int padding = getResources().getDimensionPixelSize(R.dimen.space);
        android.widget.FrameLayout wrapper = new android.widget.FrameLayout(requireContext());
        wrapper.setPadding(padding, padding / 2, padding, 0);
        wrapper.addView(input);

        new MaterialAlertDialogBuilder(requireContext())
                .setTitle(getString(R.string.booking_cancel_title, booking.code()))
                .setMessage(R.string.booking_cancel_message)
                .setView(wrapper)
                .setNegativeButton(R.string.action_cancel, null)
                .setPositiveButton(R.string.booking_cancel, (dialog, which) -> model.cancel(
                        booking,
                        input.getText() == null ? "" : input.getText().toString().trim()))
                .show();
    }
}
