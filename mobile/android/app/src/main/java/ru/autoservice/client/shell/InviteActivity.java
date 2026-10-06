package ru.autoservice.client.shell;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;

import androidx.annotation.Nullable;

import ru.autoservice.client.App;
import ru.autoservice.client.util.InviteCodes;

/**
 * Приём ссылки-приглашения `https://<домен>/i/<код>` (Android App Links).
 *
 * <p>Своего экрана нет: код откладывается в {@link
 * ru.autoservice.client.data.local.InviteStorage}, и сразу открывается
 * оболочка. Веб-приложение заберёт код через мост — при входе или сразу,
 * если человек уже вошёл. Код сохраняется, а не передаётся в {@link Intent}:
 * между ссылкой и привязкой стоит вход, и приложение по дороге может быть
 * выгружено системой.
 */
public class InviteActivity extends Activity {

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        Uri data = getIntent() == null ? null : getIntent().getData();
        String code = InviteCodes.parse(data == null ? null : data.toString());
        if (code != null) {
            App.invites(this).remember(code);
        }

        // Оболочка одна (singleTask): уже открытая получит onNewIntent и
        // скажет странице забрать код, а не начнёт всё заново.
        Intent shell = new Intent(this, ShellActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                        | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        startActivity(shell);
        finish();
    }
}
