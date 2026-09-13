package ru.autoservice.client.ui.auth;

import android.app.Application;
import android.os.CountDownTimer;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.lifecycle.AndroidViewModel;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import ru.autoservice.client.App;
import ru.autoservice.client.R;
import ru.autoservice.client.data.repository.AuthRepository;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.common.Event;
import ru.autoservice.client.util.ApiError;
import ru.autoservice.client.util.Formats;

/**
 * Вход по SMS: запрос кода, проверка кода, обратный отсчёт до повторной отправки.
 *
 * <p>Состояние живёт здесь, а не в Activity: поворот экрана в середине ввода
 * кода не должен ни сбрасывать шаг, ни обнулять таймер повторной отправки.
 */
public class AuthViewModel extends AndroidViewModel {

    /** На каком шаге находится вход. */
    public enum Step { PHONE, CODE }

    private final AuthRepository repository;

    private final MutableLiveData<Step> step = new MutableLiveData<>(Step.PHONE);
    private final MutableLiveData<Boolean> busy = new MutableLiveData<>(false);
    private final MutableLiveData<Integer> resendIn = new MutableLiveData<>(0);
    private final MutableLiveData<String> debugCode = new MutableLiveData<>(null);
    private final Event.Bus<ApiError> errors = new Event.Bus<>();
    private final Event.Bus<Models.User> signedIn = new Event.Bus<>();

    private String phone = "";
    @Nullable private CountDownTimer resendTimer;

    public AuthViewModel(@NonNull Application application) {
        super(application);
        this.repository = App.container(application).auth();
        String last = repository.lastPhone();
        if (last != null) {
            phone = last;
        }
    }

    public LiveData<Step> step() { return step; }
    public LiveData<Boolean> busy() { return busy; }
    public LiveData<Integer> resendIn() { return resendIn; }
    public LiveData<String> debugCode() { return debugCode; }
    public LiveData<Event<ApiError>> errors() { return errors.asLiveData(); }
    public LiveData<Event<Models.User>> signedIn() { return signedIn.asLiveData(); }

    /** Телефон последнего входа — подставляем в поле, чтобы не набирать заново. */
    @NonNull
    public String phone() {
        return phone;
    }

    public boolean isSignedIn() {
        return repository.isSignedIn();
    }

    public void requestCode(@NonNull String rawPhone) {
        if (Boolean.TRUE.equals(busy.getValue())) {
            return;
        }
        // Локальная проверка до запроса: сервер всё равно нормализует номер,
        // но показать «телефон не разобрался» лучше сразу.
        String normalized = Formats.normalizePhone(rawPhone);
        if (normalized.length() < 11) {
            errors.post(new ApiError("phone_invalid",
                    getApplication().getString(R.string.error_phone), 0, null, null));
            return;
        }

        busy.setValue(true);
        repository.requestOtp(normalized, result -> {
            busy.setValue(false);
            if (!result.isSuccess() || result.value() == null) {
                errors.post(result.error());
                return;
            }
            phone = result.value().phone();
            debugCode.setValue(result.value().debugCode());
            step.setValue(Step.CODE);
            startResendCountdown(result.value().resendAfterSeconds());
        });
    }

    public void verifyCode(@NonNull String code) {
        if (Boolean.TRUE.equals(busy.getValue()) || code.trim().isEmpty()) {
            return;
        }
        busy.setValue(true);
        repository.verifyOtp(phone, code.trim(), result -> {
            busy.setValue(false);
            if (!result.isSuccess() || result.value() == null) {
                errors.post(result.error());
                return;
            }
            signedIn.post(result.value());
        });
    }

    /** Вернуться к вводу номера. */
    public void editPhone() {
        stopResendCountdown();
        debugCode.setValue(null);
        step.setValue(Step.PHONE);
    }

    public void resend() {
        Integer left = resendIn.getValue();
        if (left != null && left > 0) {
            return;
        }
        requestCode(phone);
    }

    /**
     * Обратный отсчёт до повторной отправки.
     *
     * <p>Сервер сам не даст отправить раньше (429 otp_cooldown), но кнопка,
     * которая гарантированно вернёт ошибку, — плохая кнопка.
     */
    private void startResendCountdown(int seconds) {
        stopResendCountdown();
        if (seconds <= 0) {
            resendIn.setValue(0);
            return;
        }
        resendIn.setValue(seconds);
        resendTimer = new CountDownTimer(seconds * 1000L, 1000L) {
            @Override
            public void onTick(long millisUntilFinished) {
                resendIn.setValue((int) (millisUntilFinished / 1000L));
            }

            @Override
            public void onFinish() {
                resendIn.setValue(0);
            }
        }.start();
    }

    private void stopResendCountdown() {
        if (resendTimer != null) {
            resendTimer.cancel();
            resendTimer = null;
        }
    }

    @Override
    protected void onCleared() {
        stopResendCountdown();
        super.onCleared();
    }
}
