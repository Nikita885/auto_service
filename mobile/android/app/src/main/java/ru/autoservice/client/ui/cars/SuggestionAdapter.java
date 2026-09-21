package ru.autoservice.client.ui.cars;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.List;

import ru.autoservice.client.databinding.ItemSuggestionBinding;
import ru.autoservice.client.domain.model.Models;

/** Список подсказок: марки со стрелкой вправо, модели без неё. */
public class SuggestionAdapter extends RecyclerView.Adapter<SuggestionAdapter.Holder> {

    public interface OnPick {
        void onPick(@NonNull Models.CarSuggestion item);
    }

    private final List<Models.CarSuggestion> items = new ArrayList<>();
    private final OnPick listener;

    public SuggestionAdapter(@NonNull OnPick listener) {
        this.listener = listener;
    }

    public void submit(List<Models.CarSuggestion> next) {
        items.clear();
        if (next != null) {
            items.addAll(next);
        }
        // Список короткий (не больше двадцати строк) и перерисовывается
        // целиком на каждый ввод — DiffUtil здесь только добавил бы кода.
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        return new Holder(ItemSuggestionBinding.inflate(
                LayoutInflater.from(parent.getContext()), parent, false));
    }

    @Override
    public void onBindViewHolder(@NonNull Holder holder, int position) {
        holder.bind(items.get(position));
    }

    @Override
    public int getItemCount() {
        return items.size();
    }

    class Holder extends RecyclerView.ViewHolder {
        private final ItemSuggestionBinding views;

        Holder(@NonNull ItemSuggestionBinding views) {
            super(views.getRoot());
            this.views = views;
        }

        void bind(@NonNull Models.CarSuggestion item) {
            views.title.setText(item.title());
            views.chevron.setVisibility(item.hasModels() ? View.VISIBLE : View.GONE);
            views.getRoot().setOnClickListener(v -> listener.onPick(item));
        }
    }
}
