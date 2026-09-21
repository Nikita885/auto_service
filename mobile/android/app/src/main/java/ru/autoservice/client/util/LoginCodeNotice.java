package ru.autoservice.client.util;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;

import ru.autoservice.client.BuildConfig;
import ru.autoservice.client.R;

/**
 * Временная заглушка: код входа показывается уведомлением.
 *
 * <p>Нужна, пока у SMS-шлюза не согласован буквенный отправитель — без
 * него сообщения не уходят вовсе, и войти в приложение на живом сервере
 * нельзя. Сервер отдаёт код в ответе только для номеров из
 * `OTP_DEBUG_PHONES`; здесь он превращается в уведомление, чтобы не
 * списывать его с экрана и не лазить в логи сервера.
 *
 * <p><b>Это не push.</b> Уведомление местное: приложение рисует его само,
 * получив код в ответе на свой же запрос. Настоящие push через FCM — это
 * отдельная работа, и когда она появится, весь этот класс уйдёт.
 *
 * <p>Класс работает только в отладочной сборке (`BuildConfig.DEBUG`):
 * заглушка не должна доехать до магазина даже случайно.
 */
public final class LoginCodeNotice {

    private static final String CHANNEL_ID = "login_code";
    private static final int NOTIFICATION_ID = 1001;

    private LoginCodeNotice() {
    }

    /**
     * Показать код уведомлением. В релизной сборке не делает ничего.
     *
     * <p>Разрешения не спрашивает: спросить его может только экран, а
     * молча падать без него нельзя — код всё равно виден в самом
     * приложении, уведомление здесь лишь удобство.
     */
    public static void show(@NonNull Context context, @NonNull String code) {
        if (!BuildConfig.DEBUG || code.isEmpty() || !allowed(context)) {
            return;
        }

        ensureChannel(context);

        Notification notification = new NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_logo)
                .setContentTitle(context.getString(R.string.notice_code_title, code))
                .setContentText(context.getString(R.string.notice_code_text))
                // Код нужен здесь и сейчас, поэтому всплывающее уведомление,
                // а не тихая строчка в шторке.
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_MESSAGE)
                .setAutoCancel(true)
                .build();

        try {
            NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification);
        } catch (SecurityException ignored) {
            // Разрешение отозвали между проверкой и показом. Не повод
            // ронять экран входа: код виден в самом приложении.
        }
    }

    /** Нужно ли спрашивать разрешение на уведомления у этой версии Android. */
    public static boolean needsPermission(@NonNull Context context) {
        return BuildConfig.DEBUG
                && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && !allowed(context);
    }

    private static boolean allowed(@NonNull Context context) {
        // До Android 13 разрешение не спрашивают вовсе, и проверять нужно
        // только то, не выключил ли пользователь уведомления руками.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            int granted = ContextCompat.checkSelfPermission(
                    context, android.Manifest.permission.POST_NOTIFICATIONS);
            if (granted != PackageManager.PERMISSION_GRANTED) {
                return false;
            }
        }
        return NotificationManagerCompat.from(context).areNotificationsEnabled();
    }

    private static void ensureChannel(@NonNull Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        if (manager == null || manager.getNotificationChannel(CHANNEL_ID) != null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                context.getString(R.string.notice_channel_name),
                NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription(context.getString(R.string.notice_channel_description));
        manager.createNotificationChannel(channel);
    }
}
