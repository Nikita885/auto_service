# R8 включён в релизе: код сжимается и переименовывается — и меньше весит,
# и хуже читается при разборе APK.

# Мост страницы: методы вызываются из JavaScript по именам. Переименуй их
# R8 — и веб-приложение молча потеряет токены, «Поделиться» и отступы.
-keepclassmembers class ru.autoservice.client.shell.NativeBridge {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface

# Старый Tink из security-crypto ссылается на две аннотации статического
# анализа. В runtime они не используются; остальные missing classes
# продолжают считаться ошибкой R8.
-dontwarn com.google.errorprone.annotations.Immutable
-dontwarn javax.annotation.concurrent.GuardedBy

# Вырезаем логи из релиза: в них легко утекают токены и телефоны.
-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
    public static int i(...);
    public static int w(...);
    public static int e(...);
}
