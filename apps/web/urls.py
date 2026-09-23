from django.urls import path

from apps.web.views import (
    AdminView,
    ClientAppView,
    InviteView,
    LandingView,
    MasterView,
    android_assetlinks,
    app_manifest,
    app_service_worker,
)

app_name = "web"

urlpatterns = [
    path("", LandingView.as_view(), name="landing"),
    path("master/", MasterView.as_view(), name="master"),
    # Не "admin/" — этот префикс занят Django-админкой, которая остаётся
    # инструментом для правки справочников.
    path("admin-panel/", AdminView.as_view(), name="admin"),
    # Короткий адрес: ссылку диктуют и пересылают, и каждый лишний сегмент
    # в ней — лишний шанс потерять хвост при копировании.
    # Веб-приложение клиента для iPhone. Манифест и воркер лежат внутри
    # /app/: воркер управляет только тем, что ниже его собственного адреса.
    path("app/", ClientAppView.as_view(), name="app"),
    path("app/manifest.webmanifest", app_manifest, name="app-manifest"),
    path("app/sw.js", app_service_worker, name="app-sw"),
    path("i/<str:code>/", InviteView.as_view(), name="invite"),
    path("i/<str:code>", InviteView.as_view()),
    path(
        ".well-known/assetlinks.json",
        android_assetlinks,
        name="android-assetlinks",
    ),
]
