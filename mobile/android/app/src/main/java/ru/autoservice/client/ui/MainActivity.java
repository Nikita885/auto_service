package ru.autoservice.client.ui;

import android.content.Intent;
import android.os.Bundle;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.fragment.app.Fragment;

import ru.autoservice.client.App;
import ru.autoservice.client.R;
import ru.autoservice.client.databinding.ActivityMainBinding;
import ru.autoservice.client.ui.auth.AuthActivity;
import ru.autoservice.client.ui.booking.BookingFragment;
import ru.autoservice.client.ui.bookings.BookingsFragment;
import ru.autoservice.client.ui.profile.ProfileFragment;
import ru.autoservice.client.ui.common.InviteFlow;
import ru.autoservice.client.ui.referral.ReferralFragment;

/**
 * Главный экран: запись, свои записи, приглашения и профиль.
 *
 * <p>Фрагменты не пересоздаются при переключении вкладок, а прячутся: экран
 * записи держит живой черновик с таймером, и терять его из-за перехода на
 * соседнюю вкладку нельзя.
 */
public class MainActivity extends AppCompatActivity implements BookingFragment.OnBookingCreated {

    private static final String TAG_BOOKING = "booking";
    private static final String TAG_BOOKINGS = "bookings";
    private static final String TAG_REFERRAL = "referral";
    private static final String TAG_PROFILE = "profile";

    private ActivityMainBinding views;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Сюда можно попасть только с токеном: при выходе или протухшей сессии
        // возвращаем на экран входа, не показывая пустые экраны.
        if (!App.container(this).auth().isSignedIn()) {
            openAuth();
            return;
        }

        views = ActivityMainBinding.inflate(getLayoutInflater());
        setContentView(views.getRoot());

        // Итог привязки при входе и отложенный код для уже вошедшего.
        InviteFlow.showOutcome(this);
        InviteFlow.attachPending(this);

        if (savedInstanceState == null) {
            addFragment(new BookingFragment(), TAG_BOOKING);
            addFragment(new BookingsFragment(), TAG_BOOKINGS);
            addFragment(new ReferralFragment(), TAG_REFERRAL);
            addFragment(new ProfileFragment(), TAG_PROFILE);
            show(TAG_BOOKING);
        }

        views.bottomNav.setOnItemSelectedListener(item -> {
            int id = item.getItemId();
            if (id == R.id.nav_booking) {
                show(TAG_BOOKING);
            } else if (id == R.id.nav_bookings) {
                show(TAG_BOOKINGS);
            } else if (id == R.id.nav_referral) {
                show(TAG_REFERRAL);
            } else {
                show(TAG_PROFILE);
            }
            return true;
        });
    }

    /** Запись создана или изменилась — обновляем соседнюю вкладку. */
    @Override
    public void onBookingCreated() {
        Fragment fragment = getSupportFragmentManager().findFragmentByTag(TAG_BOOKINGS);
        if (fragment instanceof BookingsFragment) {
            ((BookingsFragment) fragment).reload();
        }
    }

    private void addFragment(@NonNull Fragment fragment, @NonNull String tag) {
        getSupportFragmentManager().beginTransaction()
                .add(R.id.container, fragment, tag)
                .hide(fragment)
                .commit();
    }

    private void show(@NonNull String tag) {
        var manager = getSupportFragmentManager();
        var transaction = manager.beginTransaction();

        for (String other : new String[]{TAG_BOOKING, TAG_BOOKINGS, TAG_REFERRAL, TAG_PROFILE}) {
            Fragment fragment = manager.findFragmentByTag(other);
            if (fragment == null) {
                continue;
            }
            if (other.equals(tag)) {
                transaction.show(fragment);
            } else {
                transaction.hide(fragment);
            }
        }
        transaction.commit();
    }

    private void openAuth() {
        Intent intent = new Intent(this, AuthActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(intent);
        finish();
    }
}
