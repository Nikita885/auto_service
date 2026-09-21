package ru.autoservice.client.ui.invite;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;

import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;

import java.util.List;

import ru.autoservice.client.App;
import ru.autoservice.client.ui.MainActivity;
import ru.autoservice.client.ui.auth.AuthActivity;

/**
 * Приём ссылки-приглашения `https://<домен>/i/<код>`.
 *
 * <p>Своего экрана нет и не нужно: активность забирает код из адреса,
 * откладывает его и сразу уходит туда, где человек может им
 * воспользоваться. Показывать здесь что-то своё значило бы вставить
 * лишний шаг между нажатием на ссылку и результатом.
 *
 * <p>Код сохраняется, а не передаётся дальше в {@link Intent}: между
 * переходом по ссылке и привязкой стоит вход по SMS, и приложение по
 * дороге может быть выгружено системой.
 */
public class InviteActivity extends AppCompatActivity {

    /** Сегмент пути перед кодом: `/i/ABC123`. */
    private static final String PATH_MARKER = "i";

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        String code = extractCode(getIntent() == null ? null : getIntent().getData());
        if (code != null) {
            App.container(this).invites().remember(code);
        }

        boolean signedIn = App.container(this).auth().isSignedIn();
        Intent next = new Intent(this, signedIn ? MainActivity.class : AuthActivity.class);
        next.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(next);
        finish();
    }

    @Nullable
    private static String extractCode(@Nullable Uri uri) {
        if (uri == null) {
            return null;
        }
        List<String> segments = uri.getPathSegments();
        // Ждём ровно `/i/<код>`. Всё остальное — чужая ссылка или обрезанная
        // по дороге: молча подставлять из неё что попало нельзя.
        if (segments.size() < 2 || !PATH_MARKER.equals(segments.get(0))) {
            return null;
        }
        String code = segments.get(1).trim();
        return code.isEmpty() ? null : code;
    }
}
