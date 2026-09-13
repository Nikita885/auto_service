package ru.autoservice.client.domain.model;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.TimeZone;

/**
 * Доменные модели — то, чем оперируют экраны.
 *
 * <p>Отдельно от DTO намеренно: транспортный формат принадлежит серверу и
 * может меняться (строки вместо чисел, новые поля, другие имена), а экраны
 * должны зависеть от смысла, а не от того, как это сегодня сериализовано.
 * Здесь уже разобранные даты, числа и готовые ответы на вопросы вроде
 * «можно ли отменить».
 *
 * <p>Все модели неизменяемы: состояние экрана меняется только через
 * ViewModel, и случайная правка объекта из адаптера невозможна.
 */
public final class Models {

    private Models() {
    }

    /* ---------------------------------------------------------- профиль */

    public static final class User {
        private final String id;
        private final String phone;
        private final String fullName;
        private final String carModel;
        private final String carPlate;

        public User(String id, String phone, String fullName, String carModel, String carPlate) {
            this.id = id;
            this.phone = phone;
            this.fullName = orEmpty(fullName);
            this.carModel = orEmpty(carModel);
            this.carPlate = orEmpty(carPlate);
        }

        public String id() { return id; }
        public String phone() { return phone; }
        public String fullName() { return fullName; }
        public String carModel() { return carModel; }
        public String carPlate() { return carPlate; }

        /** Профиль пуст — мастеру не на что смотреть, стоит попросить заполнить. */
        public boolean isIncomplete() {
            return fullName.isEmpty() || carModel.isEmpty();
        }
    }

    /* ------------------------------------------------------------ адрес */

    public static final class ServicePoint {
        private final String id;
        private final String name;
        private final String address;
        private final String phone;
        private final TimeZone zone;
        private final String opensAt;
        private final String closesAt;
        private final int postsCount;

        public ServicePoint(String id, String name, String address, String phone,
                            TimeZone zone, String opensAt, String closesAt, int postsCount) {
            this.id = id;
            this.name = name;
            this.address = address;
            this.phone = orEmpty(phone);
            this.zone = zone;
            this.opensAt = shortTime(opensAt);
            this.closesAt = shortTime(closesAt);
            this.postsCount = postsCount;
        }

        public String id() { return id; }
        public String name() { return name; }
        public String address() { return address; }
        public String phone() { return phone; }

        /** Часовой пояс точки: время визита показывается в нём, а не в поясе телефона. */
        public TimeZone zone() { return zone; }

        public int postsCount() { return postsCount; }

        /** «09:00–21:00» */
        public String workHours() {
            return opensAt + "–" + closesAt;
        }

        private static String shortTime(@Nullable String value) {
            if (value == null) {
                return "";
            }
            return value.length() >= 5 ? value.substring(0, 5) : value;
        }
    }

    /* ------------------------------------------------------------ масло */

    public static final class Oil {
        private final String id;
        private final String title;
        private final String brand;
        private final String name;
        private final String viscosity;
        private final String typeDisplay;
        private final String description;
        private final double price;
        private final double workPrice;
        private final double totalPrice;
        private final int availableQuantity;

        public Oil(String id, String title, String brand, String name, String viscosity,
                   String typeDisplay, String description, double price, double workPrice,
                   double totalPrice, int availableQuantity) {
            this.id = id;
            this.title = title;
            this.brand = orEmpty(brand);
            this.name = orEmpty(name);
            this.viscosity = orEmpty(viscosity);
            this.typeDisplay = orEmpty(typeDisplay);
            this.description = orEmpty(description);
            this.price = price;
            this.workPrice = workPrice;
            this.totalPrice = totalPrice;
            this.availableQuantity = availableQuantity;
        }

        public String id() { return id; }
        public String title() { return title; }
        public String brand() { return brand; }
        public String name() { return name; }
        public String viscosity() { return viscosity; }
        public String typeDisplay() { return typeDisplay; }
        public String description() { return description; }
        public double price() { return price; }
        public double workPrice() { return workPrice; }
        public double totalPrice() { return totalPrice; }
        public int availableQuantity() { return availableQuantity; }

        public boolean isAvailable() {
            return availableQuantity > 0;
        }
    }

    /* ------------------------------------------------------------- слот */

    public static final class Slot {
        private final String startAtRaw;
        private final Date startAt;
        private final String localTime;
        private final int freePosts;

        public Slot(String startAtRaw, Date startAt, String localTime, int freePosts) {
            this.startAtRaw = startAtRaw;
            this.startAt = startAt;
            this.localTime = localTime;
            this.freePosts = freePosts;
        }

        /**
         * Строка ровно в том виде, в каком её прислал сервер.
         * В select-slot уходит именно она: любое переформатирование на клиенте
         * рискует не совпасть со слотом на сервере.
         */
        public String startAtRaw() { return startAtRaw; }

        public Date startAt() { return startAt; }
        public String localTime() { return localTime; }
        public int freePosts() { return freePosts; }
    }

    /* ---------------------------------------------------------- черновик */

    /** Что клиент должен сделать дальше. Приходит с сервера готовым. */
    public enum NextAction {
        SELECT_POINT, SELECT_OIL, SELECT_SLOT, CONFIRM, NONE;

        public static NextAction of(@Nullable String raw) {
            if (raw == null) {
                return NONE;
            }
            switch (raw) {
                case "select_point": return SELECT_POINT;
                case "select_oil": return SELECT_OIL;
                case "select_slot": return SELECT_SLOT;
                case "confirm": return CONFIRM;
                default: return NONE;
            }
        }

        /** Номер шага для индикатора прогресса: 0..3. */
        public int stepIndex() {
            switch (this) {
                case SELECT_POINT: return 0;
                case SELECT_OIL: return 1;
                case SELECT_SLOT: return 2;
                case CONFIRM: return 3;
                default: return -1;
            }
        }
    }

    public static final class Draft {
        private final String id;
        private final boolean open;
        private final boolean alive;
        private final String closeReason;
        private final NextAction nextAction;
        private final int secondsLeft;
        @Nullable private final ServicePoint servicePoint;
        @Nullable private final Oil oil;
        @Nullable private final Date slotStart;

        public Draft(String id, boolean open, boolean alive, String closeReason,
                     NextAction nextAction, int secondsLeft,
                     @Nullable ServicePoint servicePoint, @Nullable Oil oil,
                     @Nullable Date slotStart) {
            this.id = id;
            this.open = open;
            this.alive = alive;
            this.closeReason = orEmpty(closeReason);
            this.nextAction = nextAction;
            this.secondsLeft = secondsLeft;
            this.servicePoint = servicePoint;
            this.oil = oil;
            this.slotStart = slotStart;
        }

        public String id() { return id; }

        /** Живой черновик: открыт и время ещё не вышло. Только с таким можно работать. */
        public boolean isAlive() {
            return open && alive;
        }

        /** Черновик сгорел по таймеру — показываем это отдельно от обычной отмены. */
        public boolean isExpired() {
            return "expired".equals(closeReason);
        }

        public NextAction nextAction() { return nextAction; }
        public int secondsLeft() { return secondsLeft; }

        @Nullable public ServicePoint servicePoint() { return servicePoint; }
        @Nullable public Oil oil() { return oil; }
        @Nullable public Date slotStart() { return slotStart; }
    }

    /* ------------------------------------------------------------ запись */

    public enum BookingStatus {
        PENDING, IN_PROGRESS, COMPLETED, CANCELLED_BY_CLIENT, CANCELLED_BY_MASTER, NO_SHOW, UNKNOWN;

        public static BookingStatus of(@Nullable String raw) {
            if (raw == null) {
                return UNKNOWN;
            }
            switch (raw) {
                case "pending": return PENDING;
                case "in_progress": return IN_PROGRESS;
                case "completed": return COMPLETED;
                case "cancelled_by_client": return CANCELLED_BY_CLIENT;
                case "cancelled_by_master": return CANCELLED_BY_MASTER;
                case "no_show": return NO_SHOW;
                default: return UNKNOWN;
            }
        }

        public boolean isCancelled() {
            return this == CANCELLED_BY_CLIENT || this == CANCELLED_BY_MASTER;
        }
    }

    public static final class Booking {
        private final String id;
        private final String code;
        private final BookingStatus status;
        private final String statusDisplay;
        private final ServicePoint servicePoint;
        private final String oilTitle;
        private final Date startAt;
        private final double oilPrice;
        private final double workPrice;
        private final double totalPrice;
        private final String cancelReason;
        private final boolean canCancel;

        public Booking(String id, String code, BookingStatus status, String statusDisplay,
                       ServicePoint servicePoint, String oilTitle, Date startAt,
                       double oilPrice, double workPrice, double totalPrice,
                       String cancelReason, boolean canCancel) {
            this.id = id;
            this.code = code;
            this.status = status;
            this.statusDisplay = orEmpty(statusDisplay);
            this.servicePoint = servicePoint;
            this.oilTitle = orEmpty(oilTitle);
            this.startAt = startAt;
            this.oilPrice = oilPrice;
            this.workPrice = workPrice;
            this.totalPrice = totalPrice;
            this.cancelReason = orEmpty(cancelReason);
            this.canCancel = canCancel;
        }

        public String id() { return id; }
        public String code() { return code; }
        public BookingStatus status() { return status; }
        public String statusDisplay() { return statusDisplay; }
        public ServicePoint servicePoint() { return servicePoint; }
        public String oilTitle() { return oilTitle; }
        @Nullable public Date startAt() { return startAt; }
        public double oilPrice() { return oilPrice; }
        public double workPrice() { return workPrice; }
        public double totalPrice() { return totalPrice; }
        public String cancelReason() { return cancelReason; }

        /**
         * Можно ли отменить прямо сейчас. Решает сервер — здесь только флаг из
         * ответа: иначе кнопка показывалась бы, а запрос возвращал 409.
         */
        public boolean canCancel() {
            return canCancel;
        }

        /** Часовой пояс адреса: время визита всегда в нём. */
        public TimeZone zone() {
            return servicePoint == null ? TimeZone.getDefault() : servicePoint.zone();
        }
    }

    /** Дни, в которые на точке есть свободное время. */
    public static final class AvailableDays {
        private final List<String> days;

        public AvailableDays(@Nullable List<String> days) {
            this.days = days == null ? Collections.emptyList() : days;
        }

        @NonNull
        public List<String> days() {
            return days;
        }
    }

    private static String orEmpty(@Nullable String value) {
        return value == null ? "" : value;
    }
}
