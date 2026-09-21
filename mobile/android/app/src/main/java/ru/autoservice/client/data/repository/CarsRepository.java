package ru.autoservice.client.data.repository;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import java.util.ArrayList;
import java.util.List;

import ru.autoservice.client.data.remote.ApiService;
import ru.autoservice.client.data.remote.Calls;
import ru.autoservice.client.data.remote.dto.Dtos;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.util.Result;

/**
 * Подсказки по маркам и моделям.
 *
 * <p>Поиск целиком на сервере: он умеет и транслитерацию, и разговорные
 * сокращения («мерс», «merc», «Мерседес»), и справочник пополняется без
 * обновления приложения. Клиентский поиск по загруженному списку означал
 * бы вторую реализацию тех же правил — и вечное расхождение между ними.
 */
public final class CarsRepository {

    private final ApiService api;

    public CarsRepository(@NonNull ApiService api) {
        this.api = api;
    }

    /** Марки. Пустой запрос — ходовые сверху, в порядке из справочника. */
    public void makes(@Nullable String query,
                      @NonNull Result.Callback<List<Models.CarSuggestion>> callback) {
        Calls.enqueue(api.carMakes(query), list -> {
            List<Models.CarSuggestion> items = new ArrayList<>();
            for (Dtos.CarMakeDto dto : list) {
                items.add(new Models.CarSuggestion(dto.id, dto.name, true));
            }
            return items;
        }, callback);
    }

    /** Модели выбранной марки. */
    public void models(@NonNull String makeId, @Nullable String query,
                       @NonNull Result.Callback<List<Models.CarSuggestion>> callback) {
        Calls.enqueue(api.carModels(makeId, query), this::toModels, callback);
    }

    /**
     * Поиск одной строкой по всем маркам сразу: «киа рио», «kia rio».
     *
     * <p>Нужен потому, что человек набирает марку и модель подряд, не
     * задумываясь, что это два справочника.
     */
    public void search(@NonNull String query,
                       @NonNull Result.Callback<List<Models.CarSuggestion>> callback) {
        Calls.enqueue(api.carSearch(query), this::toModels, callback);
    }

    @NonNull
    private List<Models.CarSuggestion> toModels(@NonNull List<Dtos.CarModelDto> list) {
        List<Models.CarSuggestion> items = new ArrayList<>();
        for (Dtos.CarModelDto dto : list) {
            // Заголовок склеивает сервер: собирать «марка + модель» на
            // клиенте значит однажды собрать иначе, чем в профиле.
            items.add(new Models.CarSuggestion(dto.id, dto.title, false));
        }
        return items;
    }
}
