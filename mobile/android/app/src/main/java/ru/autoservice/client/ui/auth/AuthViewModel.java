package ru.autoservice.client.ui.auth;

import android.app.Application;
import android.os.CountDownTimer;
import android.os.Handler;
import android.os.Looper;

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
 * Вход по коду: звонком, после двух неудачных звонков — в SMS. Запрос кода,
 * проверка, обратный отсчёт до повторной отправки.
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
    /** Код придёт звонком (true) или в SMS (false). */
    private final MutableLiveData<Boolean> byCall = new MutableLiveData<>(true);
    /** Сервер разрешил попросить код в SMS: звонки не помогли. */
    private final MutableLiveData<Boolean> smsAvailable = new MutableLiveData<>(false);
    /**
     * Обратный звонок (OTP_MODE=verificahub): номер, на который клиент
     * звонит сам. null — код придёт звонком или в SMS.
     */
    private final MutableLiveData<String> numberToCall = new MutableLiveData<>(null);
    /** Обратный звонок закончился неудачей — текст для экрана, опрос остановлен. */
    private final MutableLiveData<String> callEnded = new MutableLiveData<>(null);

    /** Опрос статуса обратного звонка: раз в 2 секунды, пока экран виден. */
    private static final long POLL_MS = 2000L;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable pollTask = this::poll;
    @Nullable private String session;
    private boolean visible;
    private boolean polling;
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
    public LiveData<Boolean> byCall() { return byCall; }
    public LiveData<Boolean> smsAvailable() { return smsAvailable; }
    public LiveData<String> numberToCall() { return numberToCall; }
    public LiveData<String> callEnded() { return callEnded; }
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
        request(rawPhone, false);
    }

    /** Звонок не приходит — код в SMS. Кнопка есть, только когда сервер разрешил. */
    public void requestSms() {
        Integer left = resendIn.getValue();
        if (left != null && left > 0) {
            return;
        }
        request(phone, true);
    }

    private void request(@NonNull String rawPhone, boolean sms) {
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
        repository.requestOtp(normalized, sms, result -> {
            busy.setValue(false);
            if (!result.isSuccess() || result.value() == null) {
                errors.post(result.error());
                return;
            }
            phone = result.value().phone();
            session = result.value().session();
            callEnded.setValue(null);
            numberToCall.setValue(result.value().numberToCall());
            byCall.setValue(result.value().byCall());
            smsAvailable.setValue(result.value().smsAvailable());
            debugCode.setValue(result.value().debugCode());
            step.setValue(Step.CODE);
            startResendCountdown(result.value().resendAfterSeconds());
            schedulePoll(POLL_MS);
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

    /**
     * Экран снова виден — например, клиент вернулся из «Телефона» после
     * звонка. Спрашиваем сразу, не дожидаясь очередного тика.
     */
    public void onScreenVisible() {
        visible = true;
        schedulePoll(0);
    }

    public void onScreenHidden() {
        visible = false;
        handler.removeCallbacks(pollTask);
    }

    private void schedulePoll(long delayMs) {
        handler.removeCallbacks(pollTask);
        if (session != null && visible) {
            handler.postDelayed(pollTask, delayMs);
        }
    }

    /**
     * Дозвонился ли клиент. Сбой связи или шлюза ожидание не прерывает —
     * спросим снова; отказ сервера (время вышло, звонок не подтверждён)
     * останавливает опрос: дальше только новый запрос.
     */
    private void poll() {
        String current = session;
        if (current == null || !visible || polling) {
            return;
        }
        polling = true;
        repository.checkCall(phone, current, result -> {
            polling = false;
            if (!current.equals(session)) {
                return; // клиент уже запросил новый номер или ушёл со шага
            }
            if (result.isSuccess()) {
                if (result.value() != null) {
                    session = null;
                    signedIn.post(result.value());
                    return;
                }
            } else if (!isTransient(result.error())) {
                session = null;
                String message = result.error().message();
                callEnded.setValue(message.isEmpty()
                        ? getApplication().getString(R.string.auth_call_failed) : message);
                return;
            }
            schedulePoll(POLL_MS);
        });
    }

    private static boolean isTransient(@NonNull ApiError error) {
        return error.httpStatus() == 0 || error.httpStatus() >= 500
                || "otp_unavailable".equals(error.code());
    }

    /** Вернуться к вводу номера. */
    public void editPhone() {
        session = null;
        handler.removeCallbacks(pollTask);
        stopResendCountdown();
        debugCode.setValue(null);
        step.setValue(Step.PHONE);
    }

    /** Повтор тем же способом: звонок — ещё звонок, SMS — ещё SMS. */
    public void resend() {
        Integer left = resendIn.getValue();
        if (left != null && left > 0) {
            return;
        }
        // SMS повторяем, только если сервер его разрешил; иначе (SMS ушло
        // вместо сорвавшегося звонка) снова пробуем звонок.
        boolean sms = Boolean.FALSE.equals(byCall.getValue())
                && numberToCall.getValue() == null
                && Boolean.TRUE.equals(smsAvailable.getValue());
        request(phone, sms);
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
        handler.removeCallbacks(pollTask);
        stopResendCountdown();
        super.onCleared();
    }
}
