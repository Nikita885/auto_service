package ru.autoservice.client.ui.booking;

import android.app.Application;
import android.os.CountDownTimer;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import java.util.Collections;
import java.util.Date;
import java.util.List;

import ru.autoservice.client.App;
import ru.autoservice.client.data.repository.BookingRepository;
import ru.autoservice.client.data.ws.DraftSocket;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.common.Event;
import ru.autoservice.client.util.ApiError;
import ru.autoservice.client.util.Formats;
import ru.autoservice.client.util.Result;

/**
 * Запись на замену масла.
 *
 * <p>Ход записи держит сервер: он задаёт порядок шагов, отсчитывает пять минут
 * и резервирует слот с канистрой. Здесь — отражение его состояния и загрузка
 * того, что нужно показать на текущем шаге.
 *
 * <p>Таймер на экране местный и только рисует секунды. Решение «время вышло»
 * принимает сервер: когда счётчик дошёл до нуля, состояние перечитывается, а
 * не считается истёкшим самостоятельно.
 */
public class BookingViewModel extends AndroidViewModel implements DraftSocket.Listener {

    private final BookingRepository repository;
    private final DraftSocket socket;

    private final MutableLiveData<Models.Draft> draft = new MutableLiveData<>(null);
    private final MutableLiveData<Boolean> busy = new MutableLiveData<>(false);
    private final MutableLiveData<Integer> secondsLeft = new MutableLiveData<>(0);

    private final MutableLiveData<List<Models.ServicePoint>> points =
            new MutableLiveData<>(Collections.emptyList());
    private final MutableLiveData<List<Models.Oil>> oils =
            new MutableLiveData<>(Collections.emptyList());
    private final MutableLiveData<List<String>> days =
            new MutableLiveData<>(Collections.emptyList());
    private final MutableLiveData<List<Models.Slot>> slots =
            new MutableLiveData<>(Collections.emptyList());
    private final MutableLiveData<String> selectedDay = new MutableLiveData<>(null);

    private final Event.Bus<ApiError> errors = new Event.Bus<>();
    private final Event.Bus<Models.Booking> created = new Event.Bus<>();
    private final Event.Bus<Boolean> bookingsChanged = new Event.Bus<>();

    @Nullable private CountDownTimer timer;

    public BookingViewModel(@NonNull Application application) {
        super(application);
        this.repository = App.container(application).booking();
        this.socket = App.container(application).newDraftSocket();
    }

    public LiveData<Models.Draft> draft() { return draft; }
    public LiveData<Boolean> busy() { return busy; }
    public LiveData<Integer> secondsLeft() { return secondsLeft; }
    public LiveData<List<Models.ServicePoint>> points() { return points; }
    public LiveData<List<Models.Oil>> oils() { return oils; }
    public LiveData<List<String>> days() { return days; }
    public LiveData<List<Models.Slot>> slots() { return slots; }
    public LiveData<String> selectedDay() { return selectedDay; }
    public LiveData<Event<ApiError>> errors() { return errors.asLiveData(); }
    public LiveData<Event<Models.Booking>> created() { return created.asLiveData(); }
    public LiveData<Event<Boolean>> bookingsChanged() { return bookingsChanged.asLiveData(); }

    /* ----------------------------------------------------- жизненный цикл */

    /** Экран показан: читаем состояние и подписываемся на живые обновления. */
    public void onScreenVisible() {
        refresh();
        socket.start(this);
    }

    /** Экран скрыт: канал закрываем, чтобы не держать сокет в фоне. */
    public void onScreenHidden() {
        socket.stop();
        stopTimer();
    }

    @Override
    protected void onCleared() {
        socket.stop();
        stopTimer();
        super.onCleared();
    }

    /* ------------------------------------------------------------ события */

    @Override
    public void onDraftChanged(@Nullable Models.Draft updated) {
        apply(updated);
    }

    @Override
    public void onBookingChanged() {
        bookingsChanged.post(true);
    }

    /* ------------------------------------------------------------ действия */

    public void refresh() {
        repository.currentDraft(result -> {
            if (result.isSuccess()) {
                apply(result.value());
            } else {
                errors.post(result.error());
            }
        });
    }

    public void start(boolean restart) {
        run(callback -> repository.startDraft(restart, callback));
    }

    public void selectPoint(@NonNull Models.ServicePoint point) {
        Models.Draft current = draft.getValue();
        if (current == null) {
            return;
        }
        run(callback -> repository.selectPoint(current.id(), point.id(), callback));
    }

    public void selectOil(@NonNull Models.Oil oil) {
        Models.Draft current = draft.getValue();
        if (current == null) {
            return;
        }
        run(callback -> repository.selectOil(current.id(), oil.id(), callback));
    }

    public void selectSlot(@NonNull Models.Slot slot) {
        Models.Draft current = draft.getValue();
        if (current == null) {
            return;
        }
        run(callback -> repository.selectSlot(current.id(), slot.startAtRaw(), callback));
    }

    public void cancel() {
        Models.Draft current = draft.getValue();
        if (current == null) {
            return;
        }
        run(callback -> repository.cancelDraft(current.id(), callback));
    }

    public void confirm(@NonNull String comment) {
        Models.Draft current = draft.getValue();
        if (current == null || Boolean.TRUE.equals(busy.getValue())) {
            return;
        }
        busy.setValue(true);
        repository.confirm(current.id(), comment, result -> {
            busy.setValue(false);
            if (!result.isSuccess() || result.value() == null) {
                handleFailure(result.error());
                return;
            }
            created.post(result.value());
            refresh();
        });
    }

    /** Выбор дня в шаге времени. */
    public void selectDay(@NonNull String day) {
        Models.Draft current = draft.getValue();
        if (current == null || current.servicePoint() == null) {
            return;
        }
        selectedDay.setValue(day);
        repository.slots(current.servicePoint().id(), day, result -> {
            if (result.isSuccess()) {
                slots.setValue(result.value());
            } else {
                errors.post(result.error());
            }
        });
    }

    /* ------------------------------------------------------- внутреннее */

    private interface Action {
        void run(@NonNull Result.Callback<Models.Draft> callback);
    }

    /** Шаг черновика: сервер возвращает полное состояние — просто применяем его. */
    private void run(@NonNull Action action) {
        if (Boolean.TRUE.equals(busy.getValue())) {
            return;
        }
        busy.setValue(true);
        action.run(result -> {
            busy.setValue(false);
            if (result.isSuccess()) {
                apply(result.value());
            } else {
                handleFailure(result.error());
            }
        });
    }

    /**
     * Черновик мог умереть, пока клиент думал: вышли пять минут, слот заняли,
     * масло кончилось. Во всех этих случаях правда на сервере — перечитываем.
     */
    private void handleFailure(@Nullable ApiError error) {
        if (error != null) {
            errors.post(error);
            if (error.isDraftGone()
                    || error.is(ApiError.CODE_SLOT_TAKEN)
                    || error.is(ApiError.CODE_OIL_OUT_OF_STOCK)) {
                refresh();
            }
        }
    }

    private void apply(@Nullable Models.Draft updated) {
        Models.Draft previous = draft.getValue();
        draft.setValue(updated);

        if (updated == null || !updated.isAlive()) {
            stopTimer();
            secondsLeft.setValue(0);
            return;
        }

        startTimer(updated.secondsLeft());
        loadStepData(previous, updated);
    }

    /** Данные грузим только для текущего шага и только когда он сменился. */
    private void loadStepData(@Nullable Models.Draft previous, @NonNull Models.Draft current) {
        boolean stepChanged = previous == null || previous.nextAction() != current.nextAction();

        switch (current.nextAction()) {
            case SELECT_POINT:
                if (points.getValue() == null || points.getValue().isEmpty()) {
                    repository.servicePoints(result -> {
                        if (result.isSuccess()) {
                            points.setValue(result.value());
                        } else {
                            errors.post(result.error());
                        }
                    });
                }
                break;

            case SELECT_OIL:
                if (stepChanged && current.servicePoint() != null) {
                    repository.oils(current.servicePoint().id(), result -> {
                        if (result.isSuccess()) {
                            oils.setValue(result.value());
                        } else {
                            errors.post(result.error());
                        }
                    });
                }
                break;

            case SELECT_SLOT:
                if (stepChanged && current.servicePoint() != null) {
                    loadDays(current.servicePoint());
                }
                break;

            default:
                break;
        }
    }

    private void loadDays(@NonNull Models.ServicePoint point) {
        repository.availableDays(point.id(), result -> {
            if (!result.isSuccess() || result.value() == null) {
                errors.post(result.error());
                return;
            }
            List<String> available = result.value().days();
            days.setValue(available);

            // Сразу открываем ближайший день: лишний тап ни к чему.
            if (!available.isEmpty()) {
                selectDay(available.get(0));
            } else {
                slots.setValue(Collections.emptyList());
            }
        });
    }

    /* -------------------------------------------------------------- таймер */

    private void startTimer(int seconds) {
        stopTimer();
        secondsLeft.setValue(seconds);
        if (seconds <= 0) {
            return;
        }
        timer = new CountDownTimer(seconds * 1000L, 1000L) {
            @Override
            public void onTick(long millisUntilFinished) {
                secondsLeft.setValue((int) (millisUntilFinished / 1000L));
            }

            @Override
            public void onFinish() {
                secondsLeft.setValue(0);
                // Не решаем за сервер: спрашиваем, чем всё кончилось.
                refresh();
            }
        }.start();
    }

    private void stopTimer() {
        if (timer != null) {
            timer.cancel();
            timer = null;
        }
    }

    /** Подпись дня для чипа: «пн, 11 сен». */
    @NonNull
    public String dayLabel(@NonNull String isoDay) {
        Date date = Formats.parseIso(isoDay + "T00:00:00Z");
        Models.Draft current = draft.getValue();
        if (date == null) {
            return isoDay;
        }
        return Formats.dayChip(date, current != null && current.servicePoint() != null
                ? current.servicePoint().zone()
                : java.util.TimeZone.getTimeZone("UTC"));
    }
}
