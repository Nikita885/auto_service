package ru.autoservice.client.data.repository;

import androidx.annotation.NonNull;

import java.util.ArrayList;
import java.util.List;

import ru.autoservice.client.data.remote.ApiService;
import ru.autoservice.client.data.remote.Calls;
import ru.autoservice.client.data.remote.DtoMapper;
import ru.autoservice.client.data.remote.dto.Dtos;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.util.Result;

/**
 * Реферальная программа: свой код, баллы, приглашённые.
 *
 * <p>Экраны не знают ни про матрицу, ни про линии начислений — сервер
 * присылает уже посчитанную сводку. Считать проценты на клиенте значило бы
 * иметь вторую, неизбежно расходящуюся версию правил.
 */
public final class ReferralRepository {

    private final ApiService api;

    public ReferralRepository(@NonNull ApiService api) {
        this.api = api;
    }

    public void summary(@NonNull Result.Callback<Models.Referral> callback) {
        Calls.enqueue(api.referral(), DtoMapper::toReferral, callback);
    }

    /**
     * Принять приглашение. Привязка одноразовая: сервер ответит
     * {@code referral_already_attached}, если она уже есть.
     *
     * <p>Код приводим к верхнему регистру здесь: его диктуют голосом и
     * пересылают в мессенджере, регистр по дороге теряется.
     */
    public void attach(@NonNull String code, @NonNull Result.Callback<Models.Referral> callback) {
        String normalized = code.trim().toUpperCase(java.util.Locale.ROOT);
        Calls.enqueue(
                api.attachReferral(new Dtos.AttachBody(normalized)),
                DtoMapper::toReferral,
                callback);
    }

    public void points(@NonNull Result.Callback<List<Models.PointsEntry>> callback) {
        Calls.enqueue(api.referralPoints(), page -> {
            List<Models.PointsEntry> entries = new ArrayList<>();
            if (page.results != null) {
                for (Dtos.PointsEntryDto dto : page.results) {
                    entries.add(DtoMapper.toPointsEntry(dto));
                }
            }
            return entries;
        }, callback);
    }

    public void invited(@NonNull Result.Callback<List<Models.InvitedPerson>> callback) {
        Calls.enqueue(api.referralInvited(), list -> {
            List<Models.InvitedPerson> people = new ArrayList<>();
            for (Dtos.InvitedDto dto : list) {
                people.add(DtoMapper.toInvited(dto));
            }
            return people;
        }, callback);
    }
}
