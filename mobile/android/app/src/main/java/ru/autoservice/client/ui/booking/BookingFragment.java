package ru.autoservice.client.ui.booking;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.lifecycle.ViewModelProvider;
import androidx.recyclerview.widget.GridLayoutManager;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import java.util.List;

import ru.autoservice.client.R;
import ru.autoservice.client.databinding.FragmentBookingBinding;
import ru.autoservice.client.databinding.ViewStepBinding;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.common.Ui;
import ru.autoservice.client.util.Formats;

/**
 * Экран записи: четыре шага, таймер и живое состояние.
 *
 * <p>Фрагмент ничего не решает про порядок шагов — он рисует то, что пришло с
 * сервера. Какой шаг сейчас, что уже выбрано и сколько осталось времени,
 * известно из черновика.
 */
public class BookingFragment extends Fragment {

    /** Слушатель: запись создана — соседнему экрану пора обновить список. */
    public interface OnBookingCreated {
        void onBookingCreated();
    }

    private FragmentBookingBinding views;
    private BookingViewModel model;

    private StepAdapters.Points pointsAdapter;
    private StepAdapters.Oils oilsAdapter;
    private StepAdapters.Slots slotsAdapter;
    private StepAdapters.Days daysAdapter;

    private ViewStepBinding[] stepViews;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        views = FragmentBookingBinding.inflate(inflater, container, false);
        return views.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        model = new ViewModelProvider(this).get(BookingViewModel.class);

        stepViews = new ViewStepBinding[]{
                views.step1, views.step2, views.step3, views.step4
        };

        createAdapters();
        bindActions();
        observe();
    }

    @Override
    public void onStart() {
        super.onStart();
        // Вкладки не пересоздаются, а прячутся, поэтому onStart приходит и
        // скрытому фрагменту. Живой канал нужен только видимому экрану.
        if (!isHidden()) {
            model.onScreenVisible();
        }
    }

    @Override
    public void onStop() {
        super.onStop();
        model.onScreenHidden();
    }

    @Override
    public void onHiddenChanged(boolean hidden) {
        super.onHiddenChanged(hidden);
        if (hidden) {
            model.onScreenHidden();
        } else {
            model.onScreenVisible();
        }
    }

    @Override
    public void onDestroyView() {
        // Явно рвём ссылки: иначе адаптеры держат уничтоженные вьюхи.
        views.list.setAdapter(null);
        views.days.setAdapter(null);
        views = null;
        super.onDestroyView();
    }

    /* ------------------------------------------------------------ сборка */

    private void createAdapters() {
        pointsAdapter = new StepAdapters.Points(point -> model.selectPoint(point));
        oilsAdapter = new StepAdapters.Oils(oil -> model.selectOil(oil));
        slotsAdapter = new StepAdapters.Slots(slot -> model.selectSlot(slot));
        daysAdapter = new StepAdapters.Days(day -> model.dayLabel(day), day -> model.selectDay(day));

        views.days.setAdapter(daysAdapter);
    }

    private void bindActions() {
        views.start.setOnClickListener(v -> model.start(false));

        views.drop.setOnClickListener(v -> Ui.confirm(
                requireContext(),
                getString(R.string.booking_drop_title),
                getString(R.string.booking_drop_message),
                R.string.booking_drop,
                () -> model.cancel()));

        views.confirm.setOnClickListener(v -> {
            Ui.hideKeyboard(v);
            model.confirm(views.commentInput.getText() == null
                    ? "" : views.commentInput.getText().toString().trim());
        });
    }

    private void observe() {
        model.draft().observe(getViewLifecycleOwner(), this::renderDraft);

        model.busy().observe(getViewLifecycleOwner(),
                busy -> Ui.setVisible(views.progress, Boolean.TRUE.equals(busy)));

        model.secondsLeft().observe(getViewLifecycleOwner(), this::renderTimer);

        model.points().observe(getViewLifecycleOwner(), pointsAdapter::submitList);
        model.oils().observe(getViewLifecycleOwner(), oilsAdapter::submitList);
        model.slots().observe(getViewLifecycleOwner(), slotsAdapter::submitList);

        model.days().observe(getViewLifecycleOwner(), days -> {
            daysAdapter.submitList(days);
            Ui.setVisible(views.days, days != null && !days.isEmpty());
        });

        model.selectedDay().observe(getViewLifecycleOwner(), daysAdapter::setSelected);

        model.errors().observe(getViewLifecycleOwner(), event -> {
            if (event == null) {
                return;
            }
            var error = event.consume();
            if (error != null && views != null) {
                Ui.showError(views.getRoot(), error);
            }
        });

        model.created().observe(getViewLifecycleOwner(), event -> {
            if (event == null) {
                return;
            }
            Models.Booking booking = event.consume();
            if (booking == null || views == null) {
                return;
            }
            views.commentInput.setText("");
            Ui.showMessage(views.getRoot(), getString(R.string.booking_created, booking.code()));
            notifyBookingCreated();
        });

        model.bookingsChanged().observe(getViewLifecycleOwner(), event -> {
            if (event != null && event.consume() != null) {
                notifyBookingCreated();
            }
        });
    }

    private void notifyBookingCreated() {
        if (getActivity() instanceof OnBookingCreated) {
            ((OnBookingCreated) getActivity()).onBookingCreated();
        }
    }

    /* ------------------------------------------------------------ отрисовка */

    private void renderDraft(@Nullable Models.Draft draft) {
        if (views == null) {
            return;
        }

        boolean alive = draft != null && draft.isAlive();

        Ui.setVisible(views.idle, !alive);
        Ui.setVisible(views.steps, alive);
        Ui.setVisible(views.timerCard, alive);
        Ui.setVisible(views.stepTitle, alive);
        Ui.setVisible(views.drop, alive);
        Ui.setVisible(views.list, alive);

        if (!alive) {
            views.idleText.setText(draft != null && draft.isExpired()
                    ? R.string.booking_expired
                    : R.string.booking_idle);
            views.start.setText(draft != null && draft.isExpired()
                    ? R.string.booking_restart
                    : R.string.booking_start);
            Ui.setVisible(views.days, false);
            Ui.setVisible(views.confirmPanel, false);
            return;
        }

        renderSteps(draft);
        renderStepContent(draft);
    }

    /** Индикатор: пройденные шаги — галочкой, текущий — акцентом. */
    private void renderSteps(@NonNull Models.Draft draft) {
        int current = draft.nextAction().stepIndex();
        String[] labels = {
                getString(R.string.step_point),
                getString(R.string.step_oil),
                getString(R.string.step_slot),
                getString(R.string.step_confirm)
        };

        for (int i = 0; i < stepViews.length; i++) {
            ViewStepBinding step = stepViews[i];
            boolean done = current > i;
            boolean active = current == i;

            step.stepLabel.setText(labels[i]);
            Ui.setVisible(step.stepDone, done);
            Ui.setVisible(step.stepNumber, !done);
            step.stepNumber.setText(String.valueOf(i + 1));

            step.stepBadge.setBackgroundResource(
                    done || active ? R.drawable.bg_pill_accent : R.drawable.bg_pill_muted);
            step.stepNumber.setTextColor(requireContext().getColor(
                    active ? R.color.on_accent : R.color.text_faint));
            step.stepLabel.setTextColor(requireContext().getColor(
                    active ? R.color.text : R.color.text_faint));
        }
    }

    /** Список под текущий шаг. Адаптер меняется, RecyclerView остаётся один. */
    private void renderStepContent(@NonNull Models.Draft draft) {
        RecyclerView list = views.list;

        switch (draft.nextAction()) {
            case SELECT_POINT:
                views.stepTitle.setText(R.string.step_point_title);
                useLinearList(list, pointsAdapter);
                Ui.setVisible(views.days, false);
                Ui.setVisible(views.confirmPanel, false);
                break;

            case SELECT_OIL:
                views.stepTitle.setText(R.string.step_oil_title);
                useLinearList(list, oilsAdapter);
                Ui.setVisible(views.days, false);
                Ui.setVisible(views.confirmPanel, false);
                break;

            case SELECT_SLOT:
                views.stepTitle.setText(R.string.step_slot_title);
                // Слоты — сеткой: их много и они короткие.
                if (!(list.getLayoutManager() instanceof GridLayoutManager)) {
                    list.setLayoutManager(new GridLayoutManager(requireContext(), 3));
                }
                if (list.getAdapter() != slotsAdapter) {
                    list.setAdapter(slotsAdapter);
                }
                List<String> days = model.days().getValue();
                Ui.setVisible(views.days, days != null && !days.isEmpty());
                Ui.setVisible(views.confirmPanel, false);
                break;

            case CONFIRM:
            default:
                views.stepTitle.setText(R.string.step_confirm_title);
                renderSummary(draft);
                Ui.setVisible(views.days, false);
                Ui.setVisible(views.list, false);
                Ui.setVisible(views.confirmPanel, true);
                break;
        }
    }

    private void useLinearList(@NonNull RecyclerView list, @NonNull RecyclerView.Adapter<?> adapter) {
        if (!(list.getLayoutManager() instanceof LinearLayoutManager)
                || list.getLayoutManager() instanceof GridLayoutManager) {
            list.setLayoutManager(new LinearLayoutManager(requireContext()));
        }
        if (list.getAdapter() != adapter) {
            list.setAdapter(adapter);
        }
        Ui.setVisible(list, true);
    }

    /** Сводка перед подтверждением: что, где, когда и за сколько. */
    private void renderSummary(@NonNull Models.Draft draft) {
        Models.ServicePoint point = draft.servicePoint();
        Models.Oil oil = draft.oil();
        if (point == null || oil == null || draft.slotStart() == null) {
            return;
        }

        String when = Formats.dateTime(draft.slotStart(), point.zone());
        String summary = point.name() + " · " + point.address() + "\n"
                + when + "\n"
                + oil.title() + "\n"
                + getString(R.string.confirm_oil_price) + " " + Formats.money(oil.price())
                + " · " + getString(R.string.confirm_work_price) + " " + Formats.money(oil.workPrice())
                + "\n" + getString(R.string.confirm_total) + " " + Formats.money(oil.totalPrice());

        views.summary.setText(summary);
    }

    private void renderTimer(@Nullable Integer seconds) {
        if (views == null || seconds == null) {
            return;
        }
        views.timerValue.setText(Formats.clock(seconds));
        views.timerBar.setProgress(seconds);

        // Последняя минута — красным: это понятнее, чем просто бегущие цифры.
        int color = requireContext().getColor(seconds <= 60 ? R.color.danger : R.color.accent);
        views.timerValue.setTextColor(color);
        views.timerBar.setProgressTintList(android.content.res.ColorStateList.valueOf(color));
    }
}
