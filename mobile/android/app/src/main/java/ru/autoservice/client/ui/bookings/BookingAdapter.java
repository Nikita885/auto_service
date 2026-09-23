package ru.autoservice.client.ui.bookings;

import android.view.LayoutInflater;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.DiffUtil;
import androidx.recyclerview.widget.ListAdapter;
import androidx.recyclerview.widget.RecyclerView;

import java.util.Date;

import ru.autoservice.client.R;
import ru.autoservice.client.databinding.ItemBookingBinding;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.ui.common.Ui;
import ru.autoservice.client.util.Formats;

/** Список моих записей. */
public class BookingAdapter extends ListAdapter<Models.Booking, BookingAdapter.Holder> {

    public interface OnCancel {
        void onCancel(@NonNull Models.Booking booking);
    }

    private final OnCancel onCancel;

    public BookingAdapter(@NonNull OnCancel onCancel) {
        super(new DiffUtil.ItemCallback<Models.Booking>() {
            @Override
            public boolean areItemsTheSame(@NonNull Models.Booking a, @NonNull Models.Booking b) {
                return a.id().equals(b.id());
            }

            @Override
            public boolean areContentsTheSame(@NonNull Models.Booking a, @NonNull Models.Booking b) {
                return a.status() == b.status()
                        && a.canCancel() == b.canCancel()
                        && a.cancelReason().equals(b.cancelReason());
            }
        });
        this.onCancel = onCancel;
    }

    @NonNull
    @Override
    public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        return new Holder(ItemBookingBinding.inflate(
                LayoutInflater.from(parent.getContext()), parent, false));
    }

    @Override
    public void onBindViewHolder(@NonNull Holder holder, int position) {
        holder.bind(getItem(position), onCancel);
    }

    static final class Holder extends RecyclerView.ViewHolder {

        private final ItemBookingBinding views;

        Holder(@NonNull ItemBookingBinding views) {
            super(views.getRoot());
            this.views = views;
        }

        void bind(@NonNull Models.Booking booking, @NonNull OnCancel onCancel) {
            // Время визита — в часовом поясе адреса: клиент мог уехать в другой
            // регион, но приезжать ему всё равно к местному времени сервиса.
            Date start = booking.startAt();
            if (start != null) {
                views.date.setText(Formats.dateLong(start, booking.zone()));
                views.time.setText(Formats.time(start, booking.zone()));
            }

            views.code.setText(views.getRoot().getContext()
                    .getString(R.string.booking_code, booking.code()));
            views.oil.setText(booking.oilTitle());
            views.address.setText(booking.servicePoint() == null
                    ? "" : booking.servicePoint().address());
            views.price.setText(Formats.money(booking.totalPrice()));
            boolean withPoints = booking.pointsSpent() > 0;
            Ui.setVisible(views.paid, withPoints);
            if (withPoints) {
                views.paid.setText(views.getRoot().getContext().getString(
                        R.string.booking_paid_points,
                        Formats.money(booking.paidAmount()),
                        Formats.money(booking.pointsSpent())));
            }

            views.status.setText(booking.statusDisplay());
            views.status.setBackgroundResource(R.drawable.bg_chip);
            views.status.setTextColor(views.getRoot().getContext().getColor(statusColor(booking)));

            boolean hasReason = !booking.cancelReason().isEmpty();
            Ui.setVisible(views.reason, hasReason);
            if (hasReason) {
                views.reason.setText(booking.cancelReason());
            }

            // Кнопку показываем строго по флагу сервера: он знает про дедлайн
            // отмены, а угадывать его на клиенте — выдавать кнопку, которая
            // вернёт 409.
            Ui.setVisible(views.cancel, booking.canCancel());
            views.cancel.setOnClickListener(
                    booking.canCancel() ? v -> onCancel.onCancel(booking) : null);
        }

        private static int statusColor(@NonNull Models.Booking booking) {
            switch (booking.status()) {
                case COMPLETED:
                    return R.color.ok;
                case IN_PROGRESS:
                    return R.color.warn;
                case PENDING:
                    return R.color.info;
                default:
                    return R.color.danger;
            }
        }
    }
}
