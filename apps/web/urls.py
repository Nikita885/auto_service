from django.urls import path

from apps.web.views import AdminView, ClientView, MasterView

app_name = "web"

urlpatterns = [
    path("", ClientView.as_view(), name="client"),
    path("master/", MasterView.as_view(), name="master"),
    # Не "admin/" — этот префикс занят Django-админкой, которая остаётся
    # инструментом для правки справочников.
    path("admin-panel/", AdminView.as_view(), name="admin"),
]
