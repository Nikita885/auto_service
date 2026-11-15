from django.urls import path

from apps.assistant.views import AssistantReportView, AssistantView

app_name = "assistant"

urlpatterns = [
    path("", AssistantView.as_view(), name="assistant"),
    path("report/", AssistantReportView.as_view(), name="report"),
]
