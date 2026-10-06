package ru.autoservice.client.shell;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.splashscreen.SplashScreen;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;

import java.util.Arrays;
import java.util.Locale;

import ru.autoservice.client.App;
import ru.autoservice.client.BuildConfig;
import ru.autoservice.client.R;
import ru.autoservice.client.databinding.ActivityShellBinding;

/**
 * Оболочка: веб-приложение `/app/` во весь экран.
 *
 * <p>Экраны клиента пишутся один раз — в вебе — и на Android и iPhone
 * совпадают по построению. Здесь только то, чего у страницы нет: мост к
 * Keystore и системным функциям ({@link NativeBridge}), камера для сканера
 * QR, отступы под системные панели, кнопка «Назад» и экран «нет связи».
 *
 * <p>Страница рисуется под строкой состояния и навигацией, как на iPhone:
 * фон уходит под панели, а отступы веб-приложение берёт из моста. Иначе
 * одна и та же вёрстка выглядела бы на Android «в рамке».
 */
public class ShellActivity extends AppCompatActivity {

    /** Сколько держать заставку, если страница не ответила: дальше покажем, что есть. */
    private static final long SPLASH_TIMEOUT_MS = 4000;

    private ActivityShellBinding views;
    private ShellPolicy policy;
    private NativeBridge bridge;
    private final Handler main = new Handler(Looper.getMainLooper());

    private volatile boolean pageShown;
    @Nullable private PermissionRequest pendingCamera;
    private ActivityResultLauncher<String> cameraPermission;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        SplashScreen splash = SplashScreen.installSplashScreen(this);
        super.onCreate(savedInstanceState);
        // Заставка висит, пока страница не нарисовала первый кадр: иначе
        // между знаком и приложением мелькает пустой тёмный экран.
        splash.setKeepOnScreenCondition(() -> !pageShown);
        main.postDelayed(() -> pageShown = true, SPLASH_TIMEOUT_MS);

        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        views = ActivityShellBinding.inflate(getLayoutInflater());
        setContentView(views.getRoot());

        policy = new ShellPolicy(BuildConfig.SITE_URL);
        bridge = new NativeBridge(this);
        cameraPermission = registerForActivityResult(
                new ActivityResultContracts.RequestPermission(), this::onCameraPermission);

        setUpInsets();
        setUpWebView();
        setUpBack();
        views.retry.setOnClickListener(v -> retry());

        if (savedInstanceState == null || views.web.restoreState(savedInstanceState) == null) {
            views.web.loadUrl(policy.startUrl());
        }
        App.setInviteListener(this, () -> main.post(this::notifyInvite));
    }

    // ------------------------------------------------------------- WebView

    @SuppressLint("SetJavaScriptEnabled") // веб-приложение и есть интерфейс
    private void setUpWebView() {
        WebView web = views.web;
        // Без этого до первого кадра страницы видна белая подложка WebView.
        web.setBackgroundColor(ContextCompat.getColor(this, R.color.bg));
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        // Видео с камеры в сканере QR стартует без отдельного касания.
        s.setMediaPlaybackRequiresUserGesture(false);
        // Файлы устройства странице не нужны: всё приходит с сервера.
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        // Размер шрифта — как в вёрстке, а не по системной настройке: иначе
        // одни и те же экраны на Android и iPhone разъезжались бы.
        s.setTextZoom(100);
        s.setUserAgentString(s.getUserAgentString() + " MoiServisAndroid/" + BuildConfig.VERSION_NAME);

        web.addJavascriptInterface(bridge, NativeBridge.NAME);
        web.setWebViewClient(new ShellClient());
        web.setWebChromeClient(new ShellChrome());
    }

    private final class ShellClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            String url = request.getUrl().toString();
            if (policy.isInternal(url)) {
                return false;
            }
            // tel:, карты, витрина сайта, чужие ссылки — системе, не в оболочку.
            openExternal(request.getUrl());
            return true;
        }

        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            bridge.trusted = policy.isInternal(url);
            showError(false);
        }

        @Override
        public void onPageCommitVisible(WebView view, String url) {
            pageShown = true;
            pushInsets();
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                showError(true);
            }
        }

        @Override
        public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                        WebResourceResponse response) {
            // 502 во время выкатки сервера — тот же «нет связи», а не страница nginx.
            if (request.isForMainFrame() && response.getStatusCode() >= 500) {
                showError(true);
            }
        }
    }

    private final class ShellChrome extends WebChromeClient {
        @Override
        public void onPermissionRequest(PermissionRequest request) {
            Uri origin = request.getOrigin();
            boolean ownPage = policy.isInternal(
                    origin.getScheme() + "://" + origin.getEncodedAuthority() + "/app/");
            boolean camera = Arrays.asList(request.getResources())
                    .contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE);
            if (!ownPage || !camera) {
                request.deny();
                return;
            }
            if (ContextCompat.checkSelfPermission(ShellActivity.this, Manifest.permission.CAMERA)
                    == PackageManager.PERMISSION_GRANTED) {
                request.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
                return;
            }
            pendingCamera = request;
            cameraPermission.launch(Manifest.permission.CAMERA);
        }
    }

    private void onCameraPermission(boolean granted) {
        PermissionRequest request = pendingCamera;
        pendingCamera = null;
        if (request == null) {
            return;
        }
        if (granted) {
            request.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
        } else {
            // Страница сама скажет «нет доступа к камере» и предложит ввести код руками.
            request.deny();
        }
    }

    private void openExternal(@NonNull Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException ignored) {
            // Нечем открыть (например, tel: на планшете без звонков) — молча.
        }
    }

    // -------------------------------------------------------------- отступы

    private void setUpInsets() {
        ViewCompat.setOnApplyWindowInsetsListener(views.getRoot(), (root, insets) -> {
            Insets bars = insets.getInsets(
                    WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());
            int ime = insets.getInsets(WindowInsetsCompat.Type.ime()).bottom;
            // Клавиатура: поднимаем страницу на её высоту, а нижний отступ
            // навигации странице больше не нужен — его закрыла клавиатура.
            root.setPadding(bars.left, 0, bars.right, ime);
            float density = getResources().getDisplayMetrics().density;
            int top = Math.round(bars.top / density);
            int bottom = ime > 0 ? 0 : Math.round(bars.bottom / density);
            bridge.insetsJson = String.format(Locale.ROOT, "{\"top\":%d,\"bottom\":%d}", top, bottom);
            pushInsets();
            return WindowInsetsCompat.CONSUMED;
        });
    }

    private void pushInsets() {
        views.web.evaluateJavascript("window.dispatchEvent(new Event('nativeinsets'))", null);
    }

    // ---------------------------------------------------------------- назад

    /**
     * «Назад» сначала спрашивает страницу: закрыть окно, сканер, вернуться
     * на первую вкладку. Страница ответила `false` — выходим, как из любого
     * приложения с первого экрана.
     */
    private void setUpBack() {
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (views.error.getVisibility() == View.VISIBLE) {
                    leave(this);
                    return;
                }
                views.web.evaluateJavascript(
                        "window.__nativeBack ? window.__nativeBack() : false",
                        handled -> {
                            if (!"true".equals(handled)) {
                                leave(this);
                            }
                        });
            }
        });
    }

    private void leave(@NonNull OnBackPressedCallback callback) {
        callback.setEnabled(false);
        getOnBackPressedDispatcher().onBackPressed();
        callback.setEnabled(true);
    }

    // ------------------------------------------------------- нет связи

    private void showError(boolean visible) {
        views.error.setVisibility(visible ? View.VISIBLE : View.GONE);
        views.web.setVisibility(visible ? View.INVISIBLE : View.VISIBLE);
        if (visible) {
            pageShown = true;
        }
    }

    private void retry() {
        showError(false);
        String url = views.web.getUrl();
        views.web.loadUrl(policy.isInternal(url) ? url : policy.startUrl());
    }

    // ------------------------------------------------------ приглашение

    @Override
    protected void onNewIntent(@NonNull Intent intent) {
        super.onNewIntent(intent);
        // Ссылку-приглашение открыли, пока приложение работало: код уже
        // отложен InviteActivity, странице остаётся его забрать.
        notifyInvite();
    }

    private void notifyInvite() {
        if (views != null) {
            views.web.evaluateJavascript("window.dispatchEvent(new Event('nativeinvite'))", null);
        }
    }

    // ------------------------------------------------- жизненный цикл

    @Override
    protected void onSaveInstanceState(@NonNull Bundle outState) {
        super.onSaveInstanceState(outState);
        views.web.saveState(outState);
    }

    @Override
    protected void onResume() {
        super.onResume();
        views.web.onResume();
    }

    @Override
    protected void onPause() {
        views.web.onPause();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        App.setInviteListener(this, null);
        main.removeCallbacksAndMessages(null);
        super.onDestroy();
    }
}
