from django.urls import path

from apps.web.views import ClientDemoView, MasterDemoView

app_name = "web"

urlpatterns = [
    path("", ClientDemoView.as_view(), name="client"),
    path("master/", MasterDemoView.as_view(), name="master"),
]
