package ru.autoservice.client.data.remote;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.ArrayList;
import java.util.List;

import ru.autoservice.client.data.remote.dto.Dtos;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.util.Formats;

/**
 * Единственное место, где транспортный формат превращается в доменный.
 *
 * <p>Здесь же разбираются мелочи протокола: деньги приходят строками
 * («3900.00»), даты — строками ISO, часовой пояс — идентификатором. Если
 * сервер однажды начнёт присылать числа, поправить нужно будет только тут.
 */
public final class DtoMapper {

    private DtoMapper() {
    }

    /* ---------------------------------------------------------- профиль */

    @NonNull
    public static Models.User user(@NonNull Dtos.UserDto dto) {
        return new Models.User(dto.id, dto.phone, dto.fullName, dto.carModel, dto.carPlate);
    }

    /* ------------------------------------------------------------ адрес */

    @Nullable
    public static Models.ServicePoint point(@Nullable Dtos.ServicePointDto dto) {
        if (dto == null) {
            return null;
        }
        return new Models.ServicePoint(
                dto.id,
                dto.name,
                dto.address,
                dto.phone,
                Formats.zoneOrDefault(dto.timezone),
                dto.opensAt,
                dto.closesAt,
                dto.postsCount);
    }

    @NonNull
    public static List<Models.ServicePoint> points(@Nullable List<Dtos.ServicePointDto> list) {
        List<Models.ServicePoint> result = new ArrayList<>();
        if (list != null) {
            for (Dtos.ServicePointDto dto : list) {
                Models.ServicePoint point = point(dto);
                if (point != null) {
                    result.add(point);
                }
            }
        }
        return result;
    }

    /* ------------------------------------------------------------ масло */

    @Nullable
    public static Models.Oil oil(@Nullable Dtos.OilDto dto) {
        if (dto == null) {
            return null;
        }
        return new Models.Oil(
                dto.id,
                dto.title,
                dto.brand,
                dto.name,
                dto.viscosity,
                dto.oilTypeDisplay,
                dto.description,
                money(dto.price),
                money(dto.workPrice),
                money(dto.totalPrice),
                // В карточке черновика остатка нет — там масло уже отложено
                // за клиентом, и «сколько осталось» значения не имеет.
                dto.availableQuantity == null ? 1 : dto.availableQuantity);
    }

    @NonNull
    public static List<Models.Oil> oils(@Nullable List<Dtos.OilDto> list) {
        List<Models.Oil> result = new ArrayList<>();
        if (list != null) {
            for (Dtos.OilDto dto : list) {
                Models.Oil oil = oil(dto);
                if (oil != null) {
                    result.add(oil);
                }
            }
        }
        return result;
    }

    /* ------------------------------------------------------------- слот */

    @NonNull
    public static List<Models.Slot> slots(@Nullable Dtos.SlotsResponse response) {
        List<Models.Slot> result = new ArrayList<>();
        if (response == null || response.slots == null) {
            return result;
        }
        for (Dtos.SlotDto dto : response.slots) {
            result.add(new Models.Slot(
                    dto.startAt,
                    Formats.parseIso(dto.startAt),
                    dto.localTime,
                    dto.freePosts));
        }
        return result;
    }

    @NonNull
    public static Models.AvailableDays days(@Nullable Dtos.SlotsResponse response) {
        return new Models.AvailableDays(response == null ? null : response.availableDays);
    }

    /* ---------------------------------------------------------- черновик */

    @Nullable
    public static Models.Draft draft(@Nullable Dtos.DraftDto dto) {
        if (dto == null) {
            return null;
        }
        return new Models.Draft(
                dto.id,
                dto.isOpen,
                dto.isAlive,
                dto.closeReason,
                Models.NextAction.of(dto.nextAction),
                dto.secondsLeft,
                point(dto.servicePoint),
                oil(dto.oil),
                Formats.parseIso(dto.slotStart));
    }

    /* ------------------------------------------------------------ запись */

    @Nullable
    public static Models.Booking booking(@Nullable Dtos.BookingDto dto) {
        if (dto == null) {
            return null;
        }
        return new Models.Booking(
                dto.id,
                dto.code,
                Models.BookingStatus.of(dto.status),
                dto.statusDisplay,
                point(dto.servicePoint),
                dto.oilTitle,
                Formats.parseIso(dto.startAt),
                money(dto.oilPrice),
                money(dto.workPrice),
                money(dto.totalPrice),
                dto.cancelReason,
                dto.canCancel);
    }

    @NonNull
    public static List<Models.Booking> bookings(@Nullable Dtos.Page<Dtos.BookingDto> page) {
        List<Models.Booking> result = new ArrayList<>();
        if (page != null && page.results != null) {
            for (Dtos.BookingDto dto : page.results) {
                Models.Booking booking = booking(dto);
                if (booking != null) {
                    result.add(booking);
                }
            }
        }
        return result;
    }

    /* --------------------------------------------- реферальная программа */

    @NonNull
    public static Models.Referral toReferral(@NonNull Dtos.ReferralSummaryDto dto) {
        return new Models.Referral(
                dto.enabled,
                dto.code,
                dto.inviteUrl,
                money(dto.balance),
                dto.maxDiscountPercent,
                dto.attached,
                dto.invitedCount,
                dto.lineCounts,
                money(dto.earnedTotal),
                money(dto.spentTotal));
    }

    @NonNull
    public static Models.PointsEntry toPointsEntry(@NonNull Dtos.PointsEntryDto dto) {
        return new Models.PointsEntry(
                dto.id,
                money(dto.amount),
                dto.kindDisplay,
                dto.level,
                dto.bookingCode,
                dto.comment,
                Formats.parseIso(dto.createdAt));
    }

    @NonNull
    public static Models.InvitedPerson toInvited(@NonNull Dtos.InvitedDto dto) {
        return new Models.InvitedPerson(
                dto.name,
                dto.phoneMasked,
                Formats.parseIso(dto.joinedAt),
                dto.line,
                money(dto.earnedFrom));
    }

    /** Деньги приходят строкой вида «3900.00». Битая строка — не повод падать. */
    private static double money(@Nullable String raw) {
        if (raw == null || raw.isEmpty()) {
            return 0d;
        }
        try {
            return Double.parseDouble(raw);
        } catch (NumberFormatException e) {
            return 0d;
        }
    }
}
