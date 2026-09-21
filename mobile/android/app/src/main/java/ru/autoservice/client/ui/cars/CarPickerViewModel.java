package ru.autoservice.client.ui.cars;

import android.app.Application;
import android.os.Handler;
import android.os.Looper;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import java.util.Collections;
import java.util.List;

import ru.autoservice.client.App;
import ru.autoservice.client.data.repository.CarsRepository;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.common.Event;
import ru.autoservice.client.util.ApiError;

/** Состояние выбора автомобиля: что показываем и что ищем. */
public class CarPickerViewModel extends AndroidViewModel {

    /**
     * Пауза перед запросом после нажатия клавиши. Без неё «мерседес» — это
     * восемь запросов подряд, из которых нужен последний, и список прыгает
     * на каждой букве.
     */
    private static final long DEBOUNCE_MS = 250L;

    /**
     * С какой длины запроса начинаем искать. На одной букве сервер вернёт
     * первые двадцать позиций по алфавиту — это не подсказка, а шум.
     */
    private static final int MIN_QUERY = 2;

    private final CarsRepository repository;
    private final Handler handler = new Handler(Looper.getMainLooper());

    private final MutableLiveData<List<Models.CarSuggestion>> items =
            new MutableLiveData<>(Collections.emptyList());
    private final MutableLiveData<String> makeName = new MutableLiveData<>("");
    private final MutableLiveData<Boolean> searching = new MutableLiveData<>(false);
    private final MutableLiveData<String> customValue = new MutableLiveData<>("");
    private final Event.Bus<ApiError> errors = new Event.Bus<>();

    @Nullable private String makeId;
    @NonNull private String query = "";
    @Nullable private Runnable pending;

    public CarPickerViewModel(@NonNull Application application) {
        super(application);
        this.repository = App.container(application).cars();
    }

    public LiveData<List<Models.CarSuggestion>> items() { return items; }
    public LiveData<String> makeName() { return makeName; }

    /** Идёт поиск по всем маркам: подпись над списком другая. */
    public LiveData<Boolean> searching() { return searching; }

    /** Непустое — показываем кнопку «вписать своё» с этим текстом. */
    public LiveData<String> customValue() { return customValue; }

    public LiveData<Event<ApiError>> errors() { return errors.asLiveData(); }

    public void start() {
        if (items.getValue() == null || items.getValue().isEmpty()) {
            reload();
        }
    }

    public void onQueryChanged(@NonNull String value) {
        query = value.trim();
        customValue.setValue(query);

        if (pending != null) {
            handler.removeCallbacks(pending);
        }
        pending = this::reload;
        handler.postDelayed(pending, DEBOUNCE_MS);
    }

    public void openMake(@NonNull String id, @NonNull String name) {
        makeId = id;
        makeName.setValue(name);
        query = "";
        customValue.setValue("");
        reload();
    }

    public void backToMakes() {
        makeId = null;
        makeName.setValue("");
        query = "";
        customValue.setValue("");
        reload();
    }

    @Override
    protected void onCleared() {
        if (pending != null) {
            handler.removeCallbacks(pending);
        }
        super.onCleared();
    }

    private void reload() {
        pending = null;
        String current = query;

        if (makeId != null) {
            searching.setValue(false);
            repository.models(makeId, current, this::apply);
            return;
        }
        if (current.length() < MIN_QUERY) {
            searching.setValue(false);
            // Ничего не набрано — показываем марки, чтобы было с чего начать.
            repository.makes("", this::apply);
            return;
        }
        searching.setValue(true);
        // Имя марки входит в индекс модели, поэтому поиск по моделям
        // отвечает и на «мерс», и на «киа рио» — двух запросов не нужно.
        repository.search(current, this::apply);
    }

    private void apply(@NonNull ru.autoservice.client.util.Result<List<Models.CarSuggestion>> result) {
        if (!result.isSuccess()) {
            errors.post(result.error());
            return;
        }
        List<Models.CarSuggestion> value = result.value();
        items.setValue(value == null ? Collections.emptyList() : value);
    }
}
