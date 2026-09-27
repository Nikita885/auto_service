package ru.autoservice.client.ui.common;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import android.app.Application;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.fragment.app.FragmentActivity;
import androidx.fragment.app.FragmentManager;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.LinkedHashMap;

/**
 * Холодный старт главного экрана: первая вкладка обязана быть видна сразу.
 *
 * <p>Приложение подменено обычным {@link Application}: настоящее собирает
 * хранилище токенов на Android Keystore, которого в Robolectric нет, а
 * проверяется здесь только механика вкладок.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 34, application = Application.class)
public class TabsTest {

    private static final String[] TAGS = {"booking", "bookings", "referral", "profile"};

    /** Считает, сколько раз вкладка стартовала видимой — так, как это делают экраны. */
    public static class Probe extends Fragment {
        int visibleStarts;

        @Override
        public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                                 @Nullable Bundle savedInstanceState) {
            return new View(inflater.getContext());
        }

        @Override
        public void onStart() {
            super.onStart();
            if (!isHidden()) {
                visibleStarts++;
            }
        }
    }

    public static class Host extends FragmentActivity {
        static final int CONTAINER = View.generateViewId();

        @Override
        protected void onCreate(@Nullable Bundle savedInstanceState) {
            super.onCreate(savedInstanceState);
            FrameLayout container = new FrameLayout(this);
            container.setId(CONTAINER);
            setContentView(container);
            if (savedInstanceState == null) {
                LinkedHashMap<String, Fragment> tabs = new LinkedHashMap<>();
                for (String tag : TAGS) {
                    tabs.put(tag, new Probe());
                }
                Tabs.setUp(getSupportFragmentManager(), CONTAINER, tabs, TAGS[0]);
            }
        }
    }

    private FragmentManager manager;

    @Before
    public void coldStart() {
        Host host = Robolectric.buildActivity(Host.class).setup().get();
        manager = host.getSupportFragmentManager();
    }

    private Probe tab(String tag) {
        Fragment fragment = manager.findFragmentByTag(tag);
        assertNotNull("вкладка " + tag + " не добавлена", fragment);
        return (Probe) fragment;
    }

    @Test
    public void firstTabIsVisibleRightAfterColdStart() {
        Probe booking = tab("booking");
        assertFalse("первая вкладка скрыта после холодного старта", booking.isHidden());
        assertEquals(View.VISIBLE, booking.requireView().getVisibility());
        // Экран грузит данные в onStart только видимым — это и была пустая «Запись».
        assertEquals(1, booking.visibleStarts);
    }

    @Test
    public void otherTabsAreAddedButHidden() {
        for (int i = 1; i < TAGS.length; i++) {
            Probe other = tab(TAGS[i]);
            assertTrue(TAGS[i] + " видна вместе с первой", other.isHidden());
            assertEquals(0, other.visibleStarts);
        }
    }

    @Test
    public void switchingShowsExactlyOneTab() {
        Tabs.show(manager, TAGS, "referral");
        manager.executePendingTransactions();
        for (String tag : TAGS) {
            assertEquals(tag, !tag.equals("referral"), tab(tag).isHidden());
        }

        Tabs.show(manager, TAGS, "booking");
        manager.executePendingTransactions();
        assertFalse(tab("booking").isHidden());
        assertTrue(tab("referral").isHidden());
    }
}
