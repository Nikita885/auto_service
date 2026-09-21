package ru.autoservice.client.ui.referral;

import android.content.Context;
import android.view.LayoutInflater;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.List;
import java.util.TimeZone;

import ru.autoservice.client.R;
import ru.autoservice.client.databinding.ItemInvitedBinding;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.util.Formats;

/** Кого клиент привёл лично и сколько это ему принесло. */
public class InvitedAdapter extends RecyclerView.Adapter<InvitedAdapter.Holder> {

    private final List<Models.InvitedPerson> items = new ArrayList<>();

    public void submit(List<Models.InvitedPerson> next) {
        items.clear();
        if (next != null) {
            items.addAll(next);
        }
        notifyDataSetChanged();
    }

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        return new Holder(ItemInvitedBinding.inflate(
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
        private final ItemInvitedBinding views;

        Holder(@NonNull ItemInvitedBinding views) {
            super(views.getRoot());
            this.views = views;
        }

        void bind(@NonNull Models.InvitedPerson person) {
            Context context = views.getRoot().getContext();
            views.name.setText(person.name());

            StringBuilder meta = new StringBuilder(person.phoneMasked());
            // Линия важна: из-за спиловера приглашённый нередко оказывается
            // не под тем, кто его позвал, и вопрос «почему он на второй»
            // возникает сразу.
            meta.append(" · ").append(context.getString(R.string.referral_line, person.line()));
            if (person.joinedAt() != null) {
                meta.append(" · ").append(context.getString(
                        R.string.referral_joined,
                        Formats.dateLong(person.joinedAt(), TimeZone.getDefault())));
            }
            views.meta.setText(meta.toString());

            views.earned.setText(Formats.money(person.earnedFrom()));
        }
    }
}
