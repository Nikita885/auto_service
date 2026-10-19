from django.urls import path

from apps.assistant.views import AssistantView

app_name = "assistant"

urlpatterns = [path("", AssistantView.as_view(), name="assistant")]
