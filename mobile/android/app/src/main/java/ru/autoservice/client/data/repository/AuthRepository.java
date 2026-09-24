package ru.autoservice.client.data.repository;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import ru.autoservice.client.data.local.InviteStorage;
import ru.autoservice.client.data.local.TokenStorage;
import ru.autoservice.client.data.remote.ApiService;
import ru.autoservice.client.data.remote.Calls;
import ru.autoservice.client.data.remote.DtoMapper;
import ru.autoservice.client.data.remote.dto.Dtos;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.util.Formats;
import ru.autoservice.client.util.Result;

/**
 * Вход по SMS и профиль.
 *
 * <p>Репозиторий — единственный, кто знает про токены: экраны получают только
 * пользователя и результат. Так «забыть сохранить refresh» можно ровно в
 * одном месте, а не в каждом фрагменте.
 */
public final class AuthRepository {

    private final InviteStorage invites;

    private final ApiService api;
    private final TokenStorage storage;

    public AuthRepository(@NonNull ApiService api, @NonNull TokenStorage storage, @NonNull InviteStorage invites) {
        this.invites = invites;
        this.api = api;
        this.storage = storage;
    }

    /** Результат запроса кода: сколько ждать до повтора и код для отладки. */
    public static final class OtpRequested {
        private final String phone;
        private final int resendAfterSeconds;
        @Nullable private final String debugCode;

        OtpRequested(String phone, int resendAfterSeconds, @Nullable String debugCode) {
            this.phone = phone;
            this.resendAfterSeconds = resendAfterSeconds;
            this.debugCode = debugCode;
        }

        public String phone() { return phone; }
        public int resendAfterSeconds() { return resendAfterSeconds; }

        /** Приходит только с сервера разработки — в проде здесь null. */
        @Nullable public String debugCode() { return debugCode; }
    }

    /**
     * Запросить код. Телефон нормализуется до E.164 прямо здесь: «8 900…» и
     * «+7 900…» должны попасть в один аккаунт.
     */
    public void requestOtp(@NonNull String rawPhone, @NonNull Result.Callback<OtpRequested> callback) {
        String phone = Formats.normalizePhone(rawPhone);
        Calls.enqueue(
                api.requestOtp(new Dtos.OtpRequestBody(phone)),
                dto -> new OtpRequested(dto.phone, dto.resendAfterSeconds, dto.debugCode),
                callback);
    }

    /** Проверить код и войти. При успехе токены уже сохранены. */
    public void verifyOtp(@NonNull String rawPhone, @NonNull String code,
                          @NonNull Result.Callback<Models.User> callback) {
        String phone = Formats.normalizePhone(rawPhone);

        // Код из ссылки, QR или Google Play уходит вместе со входом: сервер
        // привяжет человека сам, вводить код руками не придётся.
        String invite = invites.pending();
        Calls.enqueue(api.verifyOtp(new Dtos.OtpVerifyBody(phone, code, invite == null ? "" : invite)), result -> {
            if (!result.isSuccess() || result.value() == null) {
                callback.onResult(Result.failure(result.error()));
                return;
            }
            Dtos.TokenPair pair = result.value();
            storage.saveTokens(pair.access, pair.refresh);
            storage.savePhone(phone);
            if (pair.invite != null) {
                invites.clear();
                boolean attached = "attached".equals(pair.invite.status);
                // «Уже принято» — не новость для человека, молчим.
                if (attached || !"referral_already_attached".equals(pair.invite.code)) {
                    invites.saveOutcome(attached, pair.invite.inviterName, pair.invite.message);
                }
            }
            callback.onResult(Result.success(DtoMapper.user(pair.user)));
        });
    }

    public void me(@NonNull Result.Callback<Models.User> callback) {
        Calls.enqueue(api.me(), DtoMapper::user, callback);
    }

    public void updateProfile(@NonNull String fullName, @NonNull String carModel,
                              @NonNull String carPlate, @NonNull Result.Callback<Models.User> callback) {
        Calls.enqueue(
                api.updateProfile(new Dtos.ProfileBody(fullName, carModel, carPlate)),
                DtoMapper::user,
                callback);
    }

    public boolean isSignedIn() {
        return storage.isSignedIn();
    }

    @Nullable
    public String lastPhone() {
        return storage.lastPhone();
    }

    /**
     * Выход. Токены стираются локально — отзывать refresh на сервере не
     * просим: на чужом устройстве это всё равно не спасёт, а без сети выход
     * должен работать.
     */
    public void signOut() {
        storage.clearTokens();
    }
}
