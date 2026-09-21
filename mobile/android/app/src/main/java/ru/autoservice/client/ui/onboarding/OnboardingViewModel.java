package ru.autoservice.client.ui.onboarding;

import android.app.Application;

import androidx.annotation.NonNull;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import ru.autoservice.client.App;
import ru.autoservice.client.data.local.InviteStorage;
import ru.autoservice.client.data.repository.AuthRepository;
import ru.autoservice.client.data.repository.ReferralRepository;
import ru.autoservice.client.ui.common.Event;
import ru.autoservice.client.util.ApiError;

/**
 * Знакомство после первого входа: профиль и, если есть, код приглашения.
 *
 * <p>Порядок важен: сначала сохраняем профиль, потом пробуем привязать
 * код. Неверный код не должен стоить человеку заполненного имени — а
 * именно так и вышло бы, останови мы сохранение на ошибке привязки.
 */
public class OnboardingViewModel extends AndroidViewModel {

    private final AuthRepository auth;
    private final ReferralRepository referral;
    private final InviteStorage invites;

    private final MutableLiveData<String> car = new MutableLiveData<>("");
    private final MutableLiveData<Boolean> busy = new MutableLiveData<>(false);
    private final Event.Bus<ApiError> errors = new Event.Bus<>();
    private final Event.Bus<Boolean> done = new Event.Bus<>();
    private final Event.Bus<Boolean> inviteFailed = new Event.Bus<>();

    public OnboardingViewModel(@NonNull Application application) {
        super(application);
        this.auth = App.container(application).auth();
        this.referral = App.container(application).referral();
        this.invites = App.container(application).invites();
    }

    public LiveData<String> car() { return car; }
    public LiveData<Boolean> busy() { return busy; }
    public LiveData<Event<ApiError>> errors() { return errors.asLiveData(); }
    public LiveData<Event<Boolean>> done() { return done.asLiveData(); }

    /** Профиль сохранён, а код не подошёл: экран закроется, но скажет об этом. */
    public LiveData<Event<Boolean>> inviteFailed() { return inviteFailed.asLiveData(); }

    public void setCar(@NonNull String title) {
        car.setValue(title);
    }

    /** Код из ссылки-приглашения, если человек пришёл по ней. */
    @NonNull
    public String pendingInvite() {
        String code = invites.pending();
        return code == null ? "" : code;
    }

    public void save(@NonNull String fullName, @NonNull String plate, @NonNull String inviteCode) {
        if (Boolean.TRUE.equals(busy.getValue())) {
            return;
        }
        busy.setValue(true);

        String carModel = car.getValue() == null ? "" : car.getValue();
        auth.updateProfile(fullName.trim(), carModel, plate.trim(), result -> {
            if (!result.isSuccess()) {
                busy.setValue(false);
                errors.post(result.error());
                return;
            }
            attachThenFinish(inviteCode.trim());
        });
    }

    /** Пропустить. Профиль останется пустым — заполнить его можно в профиле. */
    public void skip() {
        done.post(true);
    }

    private void attachThenFinish(@NonNull String code) {
        if (code.isEmpty()) {
            busy.setValue(false);
            done.post(true);
            return;
        }

        referral.attach(code, result -> {
            busy.setValue(false);
            // Код одноразовый: и после успеха, и после отказа забываем его,
            // иначе отклонённое приглашение вечно подставлялось бы в поле.
            invites.clear();
            if (!result.isSuccess()) {
                inviteFailed.post(true);
            }
            done.post(true);
        });
    }
}
