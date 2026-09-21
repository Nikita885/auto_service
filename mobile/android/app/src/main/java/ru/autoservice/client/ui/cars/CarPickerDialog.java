package ru.autoservice.client.ui.cars;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.DialogFragment;
import androidx.fragment.app.FragmentManager;
import androidx.lifecycle.ViewModelProvider;
import androidx.recyclerview.widget.LinearLayoutManager;

import ru.autoservice.client.R;
import ru.autoservice.client.databinding.DialogCarPickerBinding;
import ru.autoservice.client.ui.common.SimpleTextWatcher;
import ru.autoservice.client.ui.common.Ui;

/**
 * Выбор автомобиля: подсказки по маркам и моделям.
 *
 * <p>Экран один на онбординг и на профиль — иначе выбор машины в двух
 * местах разошёлся бы по поведению. Результат возвращается через
 * {@link FragmentManager} по ключу {@link #RESULT}: так диалог не знает,
 * кто его открыл, и переживает поворот экрана.
 *
 * <p>Логика показа простая и предсказуемая. Пустой запрос — список марок,
 * нажатие на марку открывает её модели. Непустой запрос ищет сразу по
 * всем моделям: имя марки входит в их индекс, поэтому «мерс» покажет
 * мерседесы, а «киа рио» — конкретную машину. Плюс всегда доступна
 * кнопка «вписать своё»: справочник не бывает полным, и упереться в его
 * неполноту на регистрации значит потерять клиента.
 */
public class CarPickerDialog extends DialogFragment {

    public static final String RESULT = "car_picker_result";
    public static final String KEY_TITLE = "title";

    private static final String TAG = "car-picker";

    private DialogCarPickerBinding views;
    private CarPickerViewModel model;
    private SuggestionAdapter adapter;

    public static void show(@NonNull FragmentManager manager) {
        new CarPickerDialog().show(manager, TAG);
    }

    @Override
    public void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Тему задаём здесь, а не в onCreateDialog: там она уже не
        // применится — окно к тому моменту создано, и диалог останется
        // плавающим, со схлопнутым в ноль списком.
        setStyle(STYLE_NORMAL, R.style.Theme_AutoService_FullScreenDialog);
    }

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        views = DialogCarPickerBinding.inflate(inflater, container, false);
        return views.getRoot();
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        model = new ViewModelProvider(this).get(CarPickerViewModel.class);

        adapter = new SuggestionAdapter(item -> {
            if (item.hasModels()) {
                model.openMake(item.id(), item.title());
                views.query.setText("");
            } else {
                finishWith(item.title());
            }
        });
        views.list.setLayoutManager(new LinearLayoutManager(requireContext()));
        views.list.setAdapter(adapter);

        views.close.setOnClickListener(v -> dismiss());
        views.backToMakes.setOnClickListener(v -> {
            model.backToMakes();
            views.query.setText("");
        });

        views.query.addTextChangedListener(
                new SimpleTextWatcher(text -> model.onQueryChanged(text.toString())));

        observe();
        model.start();
    }

    @Override
    public void onDestroyView() {
        views = null;
        super.onDestroyView();
    }

    private void observe() {
        model.items().observe(getViewLifecycleOwner(), items -> {
            if (views == null) {
                return;
            }
            adapter.submit(items);
            boolean empty = items == null || items.isEmpty();
            views.empty.setVisibility(empty ? View.VISIBLE : View.GONE);
        });

        model.makeName().observe(getViewLifecycleOwner(), name -> updateHint());
        model.searching().observe(getViewLifecycleOwner(), searching -> updateHint());

        model.customValue().observe(getViewLifecycleOwner(), value -> {
            if (views == null) {
                return;
            }
            boolean offer = value != null && !value.isEmpty();
            views.useCustom.setVisibility(offer ? View.VISIBLE : View.GONE);
            if (offer) {
                views.useCustom.setText(getString(R.string.car_picker_custom, value));
                views.useCustom.setOnClickListener(v -> finishWith(value));
            }
        });

        model.errors().observe(getViewLifecycleOwner(), event -> {
            if (event == null || views == null) {
                return;
            }
            var error = event.consume();
            if (error != null) {
                Ui.showError(views.getRoot(), error);
            }
        });
    }

    /** Подпись над списком: марки, модели выбранной марки или результаты поиска. */
    private void updateHint() {
        if (views == null) {
            return;
        }
        String make = model.makeName().getValue();
        boolean insideMake = make != null && !make.isEmpty();
        views.backToMakes.setVisibility(insideMake ? View.VISIBLE : View.GONE);

        if (insideMake) {
            views.hint.setText(getString(R.string.car_picker_models, make));
        } else if (Boolean.TRUE.equals(model.searching().getValue())) {
            views.hint.setText(R.string.car_picker_found);
        } else {
            views.hint.setText(R.string.car_picker_makes);
        }
    }

    private void finishWith(@NonNull String title) {
        Bundle result = new Bundle();
        result.putString(KEY_TITLE, title);
        getParentFragmentManager().setFragmentResult(RESULT, result);
        dismiss();
    }
}
