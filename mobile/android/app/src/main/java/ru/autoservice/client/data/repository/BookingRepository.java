package ru.autoservice.client.data.repository;

import androidx.annotation.NonNull;

import java.util.List;

import ru.autoservice.client.data.remote.ApiService;
import ru.autoservice.client.data.remote.Calls;
import ru.autoservice.client.data.remote.DtoMapper;
import ru.autoservice.client.data.remote.dto.Dtos;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.util.Result;

/**
 * Запись: справочники, черновик и свои брони.
 *
 * <p>Порядок шагов задаёт сервер — он же держит таймер на пять минут и
 * резервирует слот с канистрой. Приложение не пытается это дублировать:
 * каждый шаг возвращает полное состояние черновика, по нему и рисуется экран.
 */
public final class BookingRepository {

    /** Предстоящие записи. */
    public static final String SCOPE_UPCOMING = "upcoming";
    /** Завершённые и отменённые. */
    public static final String SCOPE_HISTORY = "history";

    private final ApiService api;

    public BookingRepository(@NonNull ApiService api) {
        this.api = api;
    }

    /* -------------------------------------------------------- справочники */

    public void servicePoints(@NonNull Result.Callback<List<Models.ServicePoint>> callback) {
        Calls.enqueue(api.servicePoints(), DtoMapper::points, callback);
    }

    /** Масла с остатком на конкретной точке — с учётом чужих броней и черновиков. */
    public void oils(@NonNull String pointId, @NonNull Result.Callback<List<Models.Oil>> callback) {
        Calls.enqueue(api.oils(pointId), DtoMapper::oils, callback);
    }

    public void availableDays(@NonNull String pointId,
                              @NonNull Result.Callback<Models.AvailableDays> callback) {
        Calls.enqueue(api.availableDays(pointId), DtoMapper::days, callback);
    }

    public void slots(@NonNull String pointId, @NonNull String date,
                      @NonNull Result.Callback<List<Models.Slot>> callback) {
        Calls.enqueue(api.slots(pointId, date), DtoMapper::slots, callback);
    }

    /* ---------------------------------------------------------- черновик */

    /**
     * Текущее состояние записи. Успех со значением {@code null} — законный
     * ответ «запись не начинали» (сервер отдаёт 204).
     */
    public void currentDraft(@NonNull Result.Callback<Models.Draft> callback) {
        Calls.enqueue(api.currentDraft(), DtoMapper::draft, callback);
    }

    /**
     * Начать запись. Повторный вызов при живом черновике возвращает его же —
     * перезагрузка экрана не крадёт время таймера.
     *
     * @param restart true — выбросить незавершённый черновик и начать заново
     */
    public void startDraft(boolean restart, @NonNull Result.Callback<Models.Draft> callback) {
        Calls.enqueue(api.startDraft(new Dtos.StartDraftBody(restart)), DtoMapper::draft, callback);
    }

    public void selectPoint(@NonNull String draftId, @NonNull String pointId,
                            @NonNull Result.Callback<Models.Draft> callback) {
        Calls.enqueue(api.selectPoint(draftId, new Dtos.SelectPointBody(pointId)),
                DtoMapper::draft, callback);
    }

    public void selectOil(@NonNull String draftId, @NonNull String oilId,
                          @NonNull Result.Callback<Models.Draft> callback) {
        Calls.enqueue(api.selectOil(draftId, new Dtos.SelectOilBody(oilId)),
                DtoMapper::draft, callback);
    }

    /**
     * Выбрать время.
     *
     * @param startAtRaw строка ровно из ответа /slots/, без переформатирования
     */
    public void selectSlot(@NonNull String draftId, @NonNull String startAtRaw,
                           @NonNull Result.Callback<Models.Draft> callback) {
        Calls.enqueue(api.selectSlot(draftId, new Dtos.SelectSlotBody(startAtRaw)),
                DtoMapper::draft, callback);
    }

    /**
     * Подтвердить запись.
     *
     * <p>Сервер здесь заново проверяет слот и остаток масла: между выбором
     * времени и подтверждением могло пройти четыре минуты, и слот мог занять
     * другой клиент. Ошибки slot_taken и oil_out_of_stock — штатный исход.
     */
    public void confirm(@NonNull String draftId, @NonNull String comment,
                        @NonNull Result.Callback<Models.Booking> callback) {
        Calls.enqueue(api.confirmDraft(draftId, new Dtos.CommentBody(comment)),
                DtoMapper::booking, callback);
    }

    /** Прервать запись: слот и канистра освобождаются сразу. */
    public void cancelDraft(@NonNull String draftId, @NonNull Result.Callback<Models.Draft> callback) {
        Calls.enqueue(api.cancelDraft(draftId), DtoMapper::draft, callback);
    }

    /* -------------------------------------------------------- мои записи */

    public void bookings(@NonNull String scope, @NonNull Result.Callback<List<Models.Booking>> callback) {
        Calls.enqueue(api.bookings(scope), DtoMapper::bookings, callback);
    }

    public void cancelBooking(@NonNull String bookingId, @NonNull String reason,
                              @NonNull Result.Callback<Models.Booking> callback) {
        Calls.enqueue(api.cancelBooking(bookingId, new Dtos.ReasonBody(reason)),
                DtoMapper::booking, callback);
    }
}
