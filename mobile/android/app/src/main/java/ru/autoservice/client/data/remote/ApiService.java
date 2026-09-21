package ru.autoservice.client.data.remote;

import java.util.List;

import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.GET;
import retrofit2.http.PATCH;
import retrofit2.http.POST;
import retrofit2.http.Path;
import retrofit2.http.Query;
import ru.autoservice.client.data.remote.dto.Dtos;

/**
 * Контракт API. Один в один повторяет справочник из README сервера,
 * чтобы расхождение было видно сразу, а не всплывало в рантайме.
 */
public interface ApiService {

    /* ------------------------------------------------------------- вход */

    @POST("api/v1/auth/otp/request/")
    Call<Dtos.OtpRequestResponse> requestOtp(@Body Dtos.OtpRequestBody body);

    @POST("api/v1/auth/otp/verify/")
    Call<Dtos.TokenPair> verifyOtp(@Body Dtos.OtpVerifyBody body);

    @POST("api/v1/auth/token/refresh/")
    Call<Dtos.RefreshResponse> refreshToken(@Body Dtos.RefreshBody body);

    /* ---------------------------------------------------------- профиль */

    @GET("api/v1/auth/me/")
    Call<Dtos.UserDto> me();

    @PATCH("api/v1/auth/me/")
    Call<Dtos.UserDto> updateProfile(@Body Dtos.ProfileBody body);

    /* -------------------------------------------------------- справочники */

    @GET("api/v1/service-points/")
    Call<List<Dtos.ServicePointDto>> servicePoints();

    @GET("api/v1/service-points/{id}/oils/")
    Call<List<Dtos.OilDto>> oils(@Path("id") String pointId);

    /** Без параметра date приходит список дней, где есть свободное время. */
    @GET("api/v1/service-points/{id}/slots/")
    Call<Dtos.SlotsResponse> availableDays(@Path("id") String pointId);

    @GET("api/v1/service-points/{id}/slots/")
    Call<Dtos.SlotsResponse> slots(@Path("id") String pointId, @Query("date") String date);

    /* ------------------------------------------------------------ запись */

    @POST("api/v1/bookings/drafts/")
    Call<Dtos.DraftDto> startDraft(@Body Dtos.StartDraftBody body);

    /** 204, если запись не начинали. */
    @GET("api/v1/bookings/drafts/current/")
    Call<Dtos.DraftDto> currentDraft();

    @POST("api/v1/bookings/drafts/{id}/select-point/")
    Call<Dtos.DraftDto> selectPoint(@Path("id") String draftId, @Body Dtos.SelectPointBody body);

    @POST("api/v1/bookings/drafts/{id}/select-oil/")
    Call<Dtos.DraftDto> selectOil(@Path("id") String draftId, @Body Dtos.SelectOilBody body);

    @POST("api/v1/bookings/drafts/{id}/select-slot/")
    Call<Dtos.DraftDto> selectSlot(@Path("id") String draftId, @Body Dtos.SelectSlotBody body);

    @POST("api/v1/bookings/drafts/{id}/confirm/")
    Call<Dtos.BookingDto> confirmDraft(@Path("id") String draftId, @Body Dtos.CommentBody body);

    @POST("api/v1/bookings/drafts/{id}/cancel/")
    Call<Dtos.DraftDto> cancelDraft(@Path("id") String draftId);

    /* -------------------------------------------------------- мои записи */

    @GET("api/v1/bookings/")
    Call<Dtos.Page<Dtos.BookingDto>> bookings(@Query("scope") String scope);

    @POST("api/v1/bookings/{id}/cancel/")
    Call<Dtos.BookingDto> cancelBooking(@Path("id") String bookingId, @Body Dtos.ReasonBody body);

    /* --------------------------------------------- реферальная программа */

    @GET("api/v1/referral/")
    Call<Dtos.ReferralSummaryDto> referral();

    @POST("api/v1/referral/attach/")
    Call<Dtos.ReferralSummaryDto> attachReferral(@Body Dtos.AttachBody body);

    @GET("api/v1/referral/points/")
    Call<Dtos.Page<Dtos.PointsEntryDto>> referralPoints();

    @GET("api/v1/referral/invited/")
    Call<List<Dtos.InvitedDto>> referralInvited();

    /* ------------------------------------------------------- автомобили */

    @GET("api/v1/cars/makes/")
    Call<List<Dtos.CarMakeDto>> carMakes(@Query("q") String query);

    @GET("api/v1/cars/makes/{id}/models/")
    Call<List<Dtos.CarModelDto>> carModels(@Path("id") String makeId, @Query("q") String query);

    /** Поиск одной строкой: «киа рио», «kia rio», «камри». */
    @GET("api/v1/cars/search/")
    Call<List<Dtos.CarModelDto>> carSearch(@Query("q") String query);
}
