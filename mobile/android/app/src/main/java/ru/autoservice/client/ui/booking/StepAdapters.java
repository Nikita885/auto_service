package ru.autoservice.client.ui.booking;

import android.view.LayoutInflater;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.DiffUtil;
import androidx.recyclerview.widget.ListAdapter;
import androidx.recyclerview.widget.RecyclerView;

import ru.autoservice.client.R;
import ru.autoservice.client.databinding.ItemDayBinding;
import ru.autoservice.client.databinding.ItemOilBinding;
import ru.autoservice.client.databinding.ItemPointBinding;
import ru.autoservice.client.databinding.ItemSlotBinding;
import ru.autoservice.client.domain.model.Models;
import ru.autoservice.client.util.Formats;

/**
 * Адаптеры шагов записи.
 *
 * <p>Все на {@link ListAdapter} с DiffUtil: список обновляется точечно, без
 * {@code notifyDataSetChanged}, и выбранный элемент не «прыгает» при
 * очередном событии из живого канала.
 */
public final class StepAdapters {

    private StepAdapters() {
    }

    /** Выбор элемента шага. */
    public interface OnPick<T> {
        void onPick(@NonNull T item);
    }

    /* ------------------------------------------------------------ адреса */

    public static final class Points extends ListAdapter<Models.ServicePoint, Points.Holder> {

        private final OnPick<Models.ServicePoint> onPick;

        public Points(@NonNull OnPick<Models.ServicePoint> onPick) {
            super(new DiffUtil.ItemCallback<Models.ServicePoint>() {
                @Override
                public boolean areItemsTheSame(@NonNull Models.ServicePoint a, @NonNull Models.ServicePoint b) {
                    return a.id().equals(b.id());
                }

                @Override
                public boolean areContentsTheSame(@NonNull Models.ServicePoint a, @NonNull Models.ServicePoint b) {
                    return a.name().equals(b.name()) && a.address().equals(b.address());
                }
            });
            this.onPick = onPick;
        }

        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemPointBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            holder.bind(getItem(position), onPick);
        }

        static final class Holder extends RecyclerView.ViewHolder {
            private final ItemPointBinding views;

            Holder(@NonNull ItemPointBinding views) {
                super(views.getRoot());
                this.views = views;
            }

            void bind(@NonNull Models.ServicePoint point, @NonNull OnPick<Models.ServicePoint> onPick) {
                views.name.setText(point.name());
                views.address.setText(point.address());

                String posts = point.postsCount() + " "
                        + Formats.plural(point.postsCount(), "пост", "поста", "постов");
                views.hours.setText(point.workHours() + " · " + posts);

                views.getRoot().setOnClickListener(v -> onPick.onPick(point));
            }
        }
    }

    /* ------------------------------------------------------------- масла */

    public static final class Oils extends ListAdapter<Models.Oil, Oils.Holder> {

        private final OnPick<Models.Oil> onPick;

        public Oils(@NonNull OnPick<Models.Oil> onPick) {
            super(new DiffUtil.ItemCallback<Models.Oil>() {
                @Override
                public boolean areItemsTheSame(@NonNull Models.Oil a, @NonNull Models.Oil b) {
                    return a.id().equals(b.id());
                }

                @Override
                public boolean areContentsTheSame(@NonNull Models.Oil a, @NonNull Models.Oil b) {
                    return a.availableQuantity() == b.availableQuantity()
                            && a.totalPrice() == b.totalPrice();
                }
            });
            this.onPick = onPick;
        }

        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemOilBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            holder.bind(getItem(position), onPick);
        }

        static final class Holder extends RecyclerView.ViewHolder {
            private final ItemOilBinding views;

            Holder(@NonNull ItemOilBinding views) {
                super(views.getRoot());
                this.views = views;
            }

            void bind(@NonNull Models.Oil oil, @NonNull OnPick<Models.Oil> onPick) {
                views.brand.setText(oil.brand());
                views.name.setText(oil.name() + " " + oil.viscosity());
                views.price.setText(Formats.money(oil.totalPrice()));

                String availability = oil.isAvailable()
                        ? views.getRoot().getContext()
                            .getString(R.string.oil_available, oil.availableQuantity())
                        : views.getRoot().getContext().getString(R.string.oil_out_of_stock);
                views.meta.setText(oil.typeDisplay() + " · " + availability);

                // Закончившееся масло видно, но выбрать нельзя: иначе сервер
                // ответит 409, и клиент не поймёт, за что.
                views.getRoot().setEnabled(oil.isAvailable());
                views.getRoot().setAlpha(oil.isAvailable() ? 1f : 0.5f);
                views.getRoot().setOnClickListener(
                        oil.isAvailable() ? v -> onPick.onPick(oil) : null);
            }
        }
    }

    /* ------------------------------------------------------------- слоты */

    public static final class Slots extends ListAdapter<Models.Slot, Slots.Holder> {

        private final OnPick<Models.Slot> onPick;

        public Slots(@NonNull OnPick<Models.Slot> onPick) {
            super(new DiffUtil.ItemCallback<Models.Slot>() {
                @Override
                public boolean areItemsTheSame(@NonNull Models.Slot a, @NonNull Models.Slot b) {
                    return a.startAtRaw().equals(b.startAtRaw());
                }

                @Override
                public boolean areContentsTheSame(@NonNull Models.Slot a, @NonNull Models.Slot b) {
                    return a.freePosts() == b.freePosts();
                }
            });
            this.onPick = onPick;
        }

        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemSlotBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            holder.bind(getItem(position), onPick);
        }

        static final class Holder extends RecyclerView.ViewHolder {
            private final ItemSlotBinding views;

            Holder(@NonNull ItemSlotBinding views) {
                super(views.getRoot());
                this.views = views;
            }

            void bind(@NonNull Models.Slot slot, @NonNull OnPick<Models.Slot> onPick) {
                views.time.setText(slot.localTime());
                views.free.setText(views.getRoot().getContext()
                        .getString(R.string.slot_free_posts, slot.freePosts()));
                views.getRoot().setOnClickListener(v -> onPick.onPick(slot));
            }
        }
    }

    /* --------------------------------------------------------------- дни */

    public static final class Days extends ListAdapter<String, Days.Holder> {

        private final OnPick<String> onPick;
        private final LabelProvider labels;

        private String selected;

        /** Подпись дня зависит от часового пояса точки — её знает ViewModel. */
        public interface LabelProvider {
            @NonNull
            String label(@NonNull String isoDay);
        }

        public Days(@NonNull LabelProvider labels, @NonNull OnPick<String> onPick) {
            super(new DiffUtil.ItemCallback<String>() {
                @Override
                public boolean areItemsTheSame(@NonNull String a, @NonNull String b) {
                    return a.equals(b);
                }

                @Override
                public boolean areContentsTheSame(@NonNull String a, @NonNull String b) {
                    return a.equals(b);
                }
            });
            this.labels = labels;
            this.onPick = onPick;
        }

        public void setSelected(String day) {
            String previous = selected;
            selected = day;
            // Перерисовываем только два чипа, а не весь список.
            notifyItemRangeChanged(0, getItemCount(), previous);
        }

        @NonNull
        @Override
        public Holder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
            return new Holder(ItemDayBinding.inflate(
                    LayoutInflater.from(parent.getContext()), parent, false));
        }

        @Override
        public void onBindViewHolder(@NonNull Holder holder, int position) {
            String day = getItem(position);
            holder.bind(day, labels.label(day), day.equals(selected), onPick);
        }

        static final class Holder extends RecyclerView.ViewHolder {
            private final ItemDayBinding views;

            Holder(@NonNull ItemDayBinding views) {
                super(views.getRoot());
                this.views = views;
            }

            void bind(@NonNull String day, @NonNull String label, boolean isSelected,
                      @NonNull OnPick<String> onPick) {
                views.dayLabel.setText(label);
                views.dayCard.setStrokeColor(views.getRoot().getContext().getColor(
                        isSelected ? R.color.accent : R.color.border));
                views.dayLabel.setTextColor(views.getRoot().getContext().getColor(
                        isSelected ? R.color.accent : R.color.text));
                views.getRoot().setOnClickListener(v -> onPick.onPick(day));
            }
        }
    }
}
