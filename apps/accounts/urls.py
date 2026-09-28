from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from apps.accounts.views import (
    MeView,
    OtpCallStatusView,
    OtpRequestView,
    OtpVerifyView,
    StaffLoginView,
)

app_name = "accounts"

urlpatterns = [
    path("otp/request/", OtpRequestView.as_view(), name="otp-request"),
    path("otp/verify/", OtpVerifyView.as_view(), name="otp-verify"),
    path("otp/call-status/", OtpCallStatusView.as_view(), name="otp-call-status"),
    path("staff/login/", StaffLoginView.as_view(), name="staff-login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("token/verify/", TokenVerifyView.as_view(), name="token-verify"),
    path("me/", MeView.as_view(), name="me"),
]
