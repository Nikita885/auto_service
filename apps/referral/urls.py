from django.urls import path

from apps.referral.views import (
    InvitedListView,
    PointsHistoryView,
    ReferralAttachView,
    ReferralCodeCheckView,
    ReferralSummaryView,
)

app_name = "referral"

urlpatterns = [
    path("", ReferralSummaryView.as_view(), name="summary"),
    path("attach/", ReferralAttachView.as_view(), name="attach"),
    path("points/", PointsHistoryView.as_view(), name="points"),
    path("invited/", InvitedListView.as_view(), name="invited"),
    # Без авторизации: по ссылке-приглашению человек приходит раньше, чем
    # ставит приложение.
    path("codes/<str:code>/", ReferralCodeCheckView.as_view(), name="code-check"),
]
