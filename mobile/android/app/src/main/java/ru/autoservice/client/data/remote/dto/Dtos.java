package ru.autoservice.client.data.remote.dto;

import com.google.gson.annotations.SerializedName;

import java.util.List;

/**
 * Транспортные объекты API.
 *
 * <p>Собраны в одном файле намеренно: это плоские структуры без поведения,
 * и держать их рядом удобнее, чем разносить по два десятка файлов. Имена
 * полей должны совпадать с контрактом сервера — R8 их не переименовывает
 * (см. proguard-rules.pro).
 */
public final class Dtos {

    private Dtos() {
    }

    /* ------------------------------------------------------------- вход */

    public static final class OtpRequestBody {
        @SerializedName("phone") public final String phone;

        public OtpRequestBody(String phone) {
            this.phone = phone;
        }
    }

    public static final class OtpRequestResponse {
        @SerializedName("phone") public String phone;
        @SerializedName("expires_at") public String expiresAt;
        @SerializedName("resend_after_seconds") public int resendAfterSeconds;
        /** Приходит только при OTP_DEBUG_EXPOSE_CODE=True на сервере разработки. */
        @SerializedName("debug_code") public String debugCode;
    }

    public static final class OtpVerifyBody {
        @SerializedName("phone") public final String phone;
        @SerializedName("code") public final String code;

        public OtpVerifyBody(String phone, String code) {
            this.phone = phone;
            this.code = code;
        }
    }

    public static final class TokenPair {
        @SerializedName("access") public String access;
        @SerializedName("refresh") public String refresh;
        @SerializedName("is_new_user") public boolean isNewUser;
        @SerializedName("user") public UserDto user;
    }

    public static final class RefreshBody {
        @SerializedName("refresh") public final String refresh;

        public RefreshBody(String refresh) {
            this.refresh = refresh;
        }
    }

    public static final class RefreshResponse {
        @SerializedName("access") public String access;
        /** Сервер ротирует refresh — новый приходит в ответе. */
        @SerializedName("refresh") public String refresh;
    }

    /* ---------------------------------------------------------- профиль */

    public static final class UserDto {
        @SerializedName("id") public String id;
        @SerializedName("phone") public String phone;
        @SerializedName("full_name") public String fullName;
        @SerializedName("role") public String role;
        @SerializedName("car_model") public String carModel;
        @SerializedName("car_plate") public String carPlate;
    }

    public static final class ProfileBody {
        @SerializedName("full_name") public final String fullName;
        @SerializedName("car_model") public final String carModel;
        @SerializedName("car_plate") public final String carPlate;

        public ProfileBody(String fullName, String carModel, String carPlate) {
            this.fullName = fullName;
            this.carModel = carModel;
            this.carPlate = carPlate;
        }
    }

    /* -------------------------------------------------------- справочники */

    public static final class ServicePointDto {
        @SerializedName("id") public String id;
        @SerializedName("name") public String name;
        @SerializedName("address") public String address;
        @SerializedName("phone") public String phone;
        @SerializedName("timezone") public String timezone;
        @SerializedName("opens_at") public String opensAt;
        @SerializedName("closes_at") public String closesAt;
        @SerializedName("slot_minutes") public int slotMinutes;
        @SerializedName("posts_count") public int postsCount;
    }

    public static final class OilDto {
        @SerializedName("id") public String id;
        @SerializedName("title") public String title;
        @SerializedName("brand") public String brand;
        @SerializedName("name") public String name;
        @SerializedName("viscosity") public String viscosity;
        @SerializedName("oil_type_display") public String oilTypeDisplay;
        @SerializedName("volume_liters") public String volumeLiters;
        @SerializedName("price") public String price;
        @SerializedName("work_price") public String workPrice;
        @SerializedName("total_price") public String totalPrice;
        @SerializedName("description") public String description;
        /** Есть только в выдаче по точке: остаток с учётом чужих броней. */
        @SerializedName("available_quantity") public Integer availableQuantity;
    }

    public static final class SlotDto {
        @SerializedName("start_at") public String startAt;
        @SerializedName("end_at") public String endAt;
        @SerializedName("local_time") public String localTime;
        @SerializedName("free_posts") public int freePosts;
    }

    public static final class SlotsResponse {
        @SerializedName("date") public String date;
        @SerializedName("available_days") public List<String> availableDays;
        @SerializedName("slots") public List<SlotDto> slots;
    }

    /* ------------------------------------------------------------ запись */

    public static final class StartDraftBody {
        @SerializedName("restart") public final boolean restart;

        public StartDraftBody(boolean restart) {
            this.restart = restart;
        }
    }

    public static final class SelectPointBody {
        @SerializedName("service_point_id") public final String servicePointId;

        public SelectPointBody(String servicePointId) {
            this.servicePointId = servicePointId;
        }
    }

    public static final class SelectOilBody {
        @SerializedName("oil_id") public final String oilId;

        public SelectOilBody(String oilId) {
            this.oilId = oilId;
        }
    }

    public static final class SelectSlotBody {
        /** Ровно та строка, что пришла из /slots/ — без преобразований. */
        @SerializedName("start_at") public final String startAt;

        public SelectSlotBody(String startAt) {
            this.startAt = startAt;
        }
    }

    public static final class CommentBody {
        @SerializedName("comment") public final String comment;

        public CommentBody(String comment) {
            this.comment = comment;
        }
    }

    public static final class ReasonBody {
        @SerializedName("reason") public final String reason;

        public ReasonBody(String reason) {
            this.reason = reason;
        }
    }

    public static final class ProgressDto {
        @SerializedName("completed") public int completed;
        @SerializedName("total") public int total;
    }

    public static final class DraftDto {
        @SerializedName("id") public String id;
        @SerializedName("step") public String step;
        @SerializedName("step_display") public String stepDisplay;
        @SerializedName("next_action") public String nextAction;
        @SerializedName("progress") public ProgressDto progress;
        @SerializedName("is_open") public boolean isOpen;
        @SerializedName("is_alive") public boolean isAlive;
        @SerializedName("close_reason") public String closeReason;
        @SerializedName("service_point") public ServicePointDto servicePoint;
        @SerializedName("oil") public OilDto oil;
        @SerializedName("slot_start") public String slotStart;
        @SerializedName("slot_end") public String slotEnd;
        @SerializedName("expires_at") public String expiresAt;
        @SerializedName("seconds_left") public int secondsLeft;
        @SerializedName("booking_id") public String bookingId;
    }

    public static final class BookingDto {
        @SerializedName("id") public String id;
        @SerializedName("code") public String code;
        @SerializedName("status") public String status;
        @SerializedName("status_display") public String statusDisplay;
        @SerializedName("service_point") public ServicePointDto servicePoint;
        @SerializedName("oil_title") public String oilTitle;
        @SerializedName("start_at") public String startAt;
        @SerializedName("end_at") public String endAt;
        @SerializedName("oil_price") public String oilPrice;
        @SerializedName("work_price") public String workPrice;
        @SerializedName("total_price") public String totalPrice;
        @SerializedName("client_comment") public String clientComment;
        @SerializedName("cancel_reason") public String cancelReason;
        @SerializedName("can_cancel") public boolean canCancel;
    }

    /** Постраничная выдача списка записей. */
    public static final class Page<T> {
        @SerializedName("count") public int count;
        @SerializedName("next") public String next;
        @SerializedName("previous") public String previous;
        @SerializedName("results") public List<T> results;
    }

    /** Конверт ошибки: поле error с кодом, текстом и подробностями. */
    public static final class ErrorEnvelope {
        @SerializedName("error") public ErrorBody error;

        public static final class ErrorBody {
            @SerializedName("code") public String code;
            @SerializedName("message") public String message;
            @SerializedName("details") public Details details;
        }

        public static final class Details {
            @SerializedName("retry_after") public Integer retryAfter;
            @SerializedName("attempts_left") public Integer attemptsLeft;
        }
    }

    /** Событие WebSocket-канала: тип события и полезная нагрузка. */
    public static final class SocketEvent {
        @SerializedName("event") public String event;
        @SerializedName("payload") public DraftDto payload;
    }

    /* --------------------------------------------- реферальная программа */

    public static final class ReferralSummaryDto {
        @SerializedName("enabled") public boolean enabled;
        @SerializedName("code") public String code;
        @SerializedName("invite_url") public String inviteUrl;
        @SerializedName("balance") public String balance;
        @SerializedName("max_discount_percent") public int maxDiscountPercent;
        @SerializedName("level_percents") public List<String> levelPercents;
        @SerializedName("attached") public boolean attached;
        @SerializedName("sponsor_code") public String sponsorCode;
        @SerializedName("invited_count") public int invitedCount;
        @SerializedName("line_counts") public List<Integer> lineCounts;
        @SerializedName("earned_total") public String earnedTotal;
        @SerializedName("spent_total") public String spentTotal;
    }

    public static final class AttachBody {
        @SerializedName("code") public final String code;

        public AttachBody(String code) {
            this.code = code;
        }
    }

    public static final class PointsEntryDto {
        @SerializedName("id") public String id;
        @SerializedName("amount") public String amount;
        @SerializedName("kind") public String kind;
        @SerializedName("kind_display") public String kindDisplay;
        @SerializedName("level") public Integer level;
        @SerializedName("percent") public String percent;
        @SerializedName("booking_code") public String bookingCode;
        @SerializedName("comment") public String comment;
        @SerializedName("created_at") public String createdAt;
    }

    public static final class InvitedDto {
        @SerializedName("name") public String name;
        @SerializedName("phone_masked") public String phoneMasked;
        @SerializedName("joined_at") public String joinedAt;
        @SerializedName("line") public int line;
        @SerializedName("earned_from") public String earnedFrom;
    }

    /* ------------------------------------------------------- автомобили */

    public static final class CarMakeDto {
        @SerializedName("id") public String id;
        @SerializedName("name") public String name;
    }

    public static final class CarModelDto {
        @SerializedName("id") public String id;
        @SerializedName("name") public String name;
        @SerializedName("make_name") public String makeName;
        /** Готовая строка «марка + модель» — ровно её кладём в профиль. */
        @SerializedName("title") public String title;
    }
}
