package ru.autoservice.client.ui.referral;

import android.content.Context;
import android.view.LayoutInflater;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.List;
import java.util.TimeZone;

import ru.autoservice.client.R;
import ru.autoservice.client.databinding.ItemPointsBinding;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.util.Formats;

/** Журнал баллов: что начислили, что списали и за что. */
public class PointsAdapter extends RecyclerView.Adapter<PointsAdapter.Holder> {

    private final List<Models.PointsEntry> items = new ArrayList<>();

    public void submit(List<Models.PointsEntry> next) {
        items.clear();
        if (next != null) {
            items.addAll(next);
        }
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        return new Holder(ItemPointsBinding.inflate(
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

    static class Holder extends RecyclerView.ViewHolder {
        private final ItemPointsBinding views;

        Holder(@NonNull ItemPointsBinding views) {
            super(views.getRoot());
            this.views = views;
        }

        void bind(@NonNull Models.PointsEntry entry) {
            Context context = views.getRoot().getContext();

            String title = entry.kindDisplay();
            if (entry.level() != null) {
                title = title + " · " + context.getString(R.string.referral_line, entry.level());
            }
            views.title.setText(title);

            views.meta.setText(meta(context, entry));

            // Знак ставим сами: сумма списания приходит отрицательной, и
            // «−150 ₽» без плюса у начисления читалось бы как опечатка.
            double amount = entry.amount();
            String sign = amount > 0 ? "+" : "−";
            views.amount.setText(sign + Formats.money(Math.abs(amount)));
            views.amount.setTextColor(ContextCompat.getColor(
                    context, entry.isAccrual() ? R.color.ok : R.color.text_soft));
        }

        @NonNull
        private String meta(@NonNull Context context, @NonNull Models.PointsEntry entry) {
            StringBuilder builder = new StringBuilder();
            if (entry.createdAt() != null) {
                builder.append(Formats.dateLong(entry.createdAt(), TimeZone.getDefault()));
            }
            if (!entry.bookingCode().isEmpty()) {
                if (builder.length() > 0) {
                    builder.append(" · ");
                }
                builder.append(context.getString(
                        R.string.referral_from_booking, entry.bookingCode()));
            }
            return builder.toString();
        }
    }
}
