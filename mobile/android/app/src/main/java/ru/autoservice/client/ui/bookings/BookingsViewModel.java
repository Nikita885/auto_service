package ru.autoservice.client.ui.bookings;

import android.app.Application;

import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import java.util.Collections;
import java.util.List;

import ru.autoservice.client.App;
import ru.autoservice.client.data.repository.BookingRepository;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.common.Event;
import ru.autoservice.client.util.ApiError;

/** Мои записи: предстоящие и история, отмена брони. */
public class BookingsViewModel extends AndroidViewModel {

    private final BookingRepository repository;

    private final MutableLiveData<List<Models.Booking>> items =
            new MutableLiveData<>(Collections.emptyList());
    private final MutableLiveData<Boolean> loading = new MutableLiveData<>(false);
    private final MutableLiveData<String> scope =
            new MutableLiveData<>(BookingRepository.SCOPE_UPCOMING);

    private final Event.Bus<ApiError> errors = new Event.Bus<>();
    private final Event.Bus<Boolean> cancelled = new Event.Bus<>();

    public BookingsViewModel(@NonNull Application application) {
        super(application);
        this.repository = App.container(application).booking();
    }

    public LiveData<List<Models.Booking>> items() { return items; }
    public LiveData<Boolean> loading() { return loading; }
    public LiveData<String> scope() { return scope; }
    public LiveData<Event<ApiError>> errors() { return errors.asLiveData(); }
    public LiveData<Event<Boolean>> cancelled() { return cancelled.asLiveData(); }

    public boolean isUpcoming() {
        return BookingRepository.SCOPE_UPCOMING.equals(scope.getValue());
    }

    public void setScope(@NonNull String value) {
        if (value.equals(scope.getValue())) {
            return;
        }
        scope.setValue(value);
        // Старый список не оставляем на экране: он относится к другой вкладке.
        items.setValue(Collections.emptyList());
        refresh();
    }

    public void refresh() {
        String current = scope.getValue();
        if (current == null) {
            return;
        }
        loading.setValue(true);
        repository.bookings(current, result -> {
            loading.setValue(false);
            if (result.isSuccess()) {
                items.setValue(result.value());
            } else {
                errors.post(result.error());
            }
        });
    }

    public void cancel(@NonNull Models.Booking booking, @NonNull String reason) {
        loading.setValue(true);
        repository.cancelBooking(booking.id(), reason, result -> {
            loading.setValue(false);
            if (!result.isSuccess()) {
                errors.post(result.error());
                // Отмена могла не пройти по дедлайну — список показывает, как есть.
                refresh();
                return;
            }
            cancelled.post(true);
            refresh();
        });
    }
}
