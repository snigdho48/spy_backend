from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

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
]
