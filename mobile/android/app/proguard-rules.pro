# R8 включён в релизе: код сжимается и переименовывается — и меньше весит,
# и хуже читается при разборе APK.

# DTO приходят и уходят через Gson по именам полей: их переименовывать нельзя.
-keep class ru.autoservice.client.data.remote.dto.** { *; }
-keepclassmembers class ru.autoservice.client.data.remote.dto.** { <fields>; }

# Retrofit: аннотации и generic-типы нужны в рантайме.
-keepattributes Signature, InnerClasses, EnclosingMethod
-keepattributes RuntimeVisibleAnnotations, RuntimeVisibleParameterAnnotations
-keepclassmembers,allowshrinking,allowobfuscation interface * {
    @retrofit2.http.* <methods>;
}
-dontwarn javax.annotation.**
-dontwarn kotlin.Unit
-dontwarn retrofit2.KotlinExtensions

# OkHttp тянет необязательные зависимости Conscrypt/BouncyCastle.
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**

# Вырезаем логи из релиза: в них легко утекают токены и телефоны.
-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
    public static int i(...);
    public static int w(...);
    public static int e(...);
}
