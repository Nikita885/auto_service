package ru.autoservice.client.ui.profile;

import android.app.Application;

import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import ru.autoservice.client.App;
import ru.autoservice.client.data.repository.AuthRepository;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.common.Event;
import ru.autoservice.client.util.ApiError;

/** Профиль: имя и автомобиль, которые видит мастер, и выход из аккаунта. */
public class ProfileViewModel extends AndroidViewModel {

    private final AuthRepository repository;

    private final MutableLiveData<Models.User> user = new MutableLiveData<>(null);
    private final MutableLiveData<Boolean> busy = new MutableLiveData<>(false);
    private final Event.Bus<ApiError> errors = new Event.Bus<>();
    private final Event.Bus<Boolean> saved = new Event.Bus<>();
    private final Event.Bus<Boolean> signedOut = new Event.Bus<>();

    public ProfileViewModel(@NonNull Application application) {
        super(application);
        this.repository = App.container(application).auth();
    }

    public LiveData<Models.User> user() { return user; }
    public LiveData<Boolean> busy() { return busy; }
    public LiveData<Event<ApiError>> errors() { return errors.asLiveData(); }
    public LiveData<Event<Boolean>> saved() { return saved.asLiveData(); }
    public LiveData<Event<Boolean>> signedOut() { return signedOut.asLiveData(); }

    public void load() {
        repository.me(result -> {
            if (result.isSuccess()) {
                user.setValue(result.value());
            } else {
                errors.post(result.error());
            }
        });
    }

    /**
     * Сохранить профиль. Телефон и роль через профиль не меняются — сервер их
     * и не примет: номер это логин.
     */
    public void save(@NonNull String fullName, @NonNull String carModel, @NonNull String carPlate) {
        if (Boolean.TRUE.equals(busy.getValue())) {
            return;
        }
        busy.setValue(true);
        repository.updateProfile(fullName.trim(), carModel.trim(), carPlate.trim(), result -> {
            busy.setValue(false);
            if (!result.isSuccess()) {
                errors.post(result.error());
                return;
            }
            user.setValue(result.value());
            saved.post(true);
        });
    }

    public void signOut() {
        repository.signOut();
        signedOut.post(true);
    }
}
