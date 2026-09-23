package ru.autoservice.client.ui.referral;

import android.app.Application;

import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import java.util.Collections;
import java.util.List;

import ru.autoservice.client.App;
import ru.autoservice.client.data.repository.ReferralRepository;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.common.Event;
import ru.autoservice.client.util.ApiError;

/**
 * Состояние экрана приглашений.
 *
 * <p>Ни процентов, ни линий здесь не считается: сводку присылает сервер
 * уже посчитанной. Вторая версия правил начисления на клиенте неизбежно
 * разошлась бы с первой, и спорить с клиентом пришлось бы о цифрах.
 */
public class ReferralViewModel extends AndroidViewModel {

    private final ReferralRepository repository;

    private final MutableLiveData<Models.Referral> summary = new MutableLiveData<>(null);
    private final MutableLiveData<List<Models.PointsEntry>> points =
            new MutableLiveData<>(Collections.emptyList());
    private final MutableLiveData<List<Models.InvitedPerson>> invited =
            new MutableLiveData<>(Collections.emptyList());
    private final MutableLiveData<Boolean> busy = new MutableLiveData<>(false);
    private final MutableLiveData<ApiError> loadError = new MutableLiveData<>(null);
    private final Event.Bus<ApiError> errors = new Event.Bus<>();
    private final Event.Bus<Boolean> attached = new Event.Bus<>();

    public ReferralViewModel(@NonNull Application application) {
        super(application);
        this.repository = App.container(application).referral();
    }

    public LiveData<Models.Referral> summary() { return summary; }
    public LiveData<List<Models.PointsEntry>> points() { return points; }
    public LiveData<List<Models.InvitedPerson>> invited() { return invited; }
    public LiveData<Boolean> busy() { return busy; }

    /** Сводка не загрузилась — экран показывает причину вместо пустых карточек. */
    public LiveData<ApiError> loadError() { return loadError; }
    public LiveData<Event<ApiError>> errors() { return errors.asLiveData(); }
    public LiveData<Event<Boolean>> attached() { return attached.asLiveData(); }

    public void load() {
        busy.setValue(true);
        repository.summary(result -> {
            busy.setValue(false);
            if (!result.isSuccess()) {
                loadError.setValue(result.error());
                return;
            }
            Models.Referral value = result.value();
            loadError.setValue(null);
            summary.setValue(value);
            // Списки грузим только когда программа включена: иначе два
            // запроса уходили бы в никуда на каждом открытии экрана.
            if (value != null && value.enabled()) {
                loadLists();
            }
        });
    }

    /**
     * Принять чужой код. Привязка одноразовая, поэтому повторное нажатие
     * вернёт ошибку с сервера — обрабатывать её на клиенте отдельно не
     * нужно, единственный источник правды тут один.
     */
    public void attach(@NonNull String code) {
        if (code.trim().isEmpty() || Boolean.TRUE.equals(busy.getValue())) {
            return;
        }
        busy.setValue(true);
        repository.attach(code, result -> {
            busy.setValue(false);
            if (!result.isSuccess()) {
                errors.post(result.error());
                return;
            }
            summary.setValue(result.value());
            attached.post(true);
        });
    }

    private void loadLists() {
        repository.points(result -> {
            if (result.isSuccess() && result.value() != null) {
                points.setValue(result.value());
            }
        });
        repository.invited(result -> {
            if (result.isSuccess() && result.value() != null) {
                invited.setValue(result.value());
            }
        });
    }
}
