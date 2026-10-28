from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.presentation.views.totp_views import (
    TotpConfirmView,
    TotpDisableView,
    TotpEnrollView,
    TotpRecoveryCodesView,
    TotpStatusView,
    TotpVerifyLoginView,
)
from apps.accounts.presentation.views.auth_views import (
    AccountDeleteView,
    AccountExportView,
    GoogleLoginView,
    LinkGoogleView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
    SetPasswordView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("google/", GoogleLoginView.as_view(), name="auth-google"),
    path("link/google/", LinkGoogleView.as_view(), name="auth-link-google"),
    path("link/password/", SetPasswordView.as_view(), name="auth-set-password"),
    path("token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("me/export/", AccountExportView.as_view(), name="auth-me-export"),
    path("me/delete/", AccountDeleteView.as_view(), name="auth-me-delete"),
    path("2fa/", TotpStatusView.as_view(), name="auth-2fa-status"),
    path("2fa/enroll/", TotpEnrollView.as_view(), name="auth-2fa-enroll"),
    path("2fa/confirm/", TotpConfirmView.as_view(), name="auth-2fa-confirm"),
    path("2fa/disable/", TotpDisableView.as_view(), name="auth-2fa-disable"),
    path("2fa/recovery-codes/", TotpRecoveryCodesView.as_view(), name="auth-2fa-recovery"),
    path("2fa/verify/", TotpVerifyLoginView.as_view(), name="auth-2fa-verify"),
]
