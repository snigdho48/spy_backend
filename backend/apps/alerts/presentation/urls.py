from django.urls import path

from apps.alerts.presentation.views.alert_views import (
    AlertDeleteView,
    AlertListView,
    AlertMarkAllReadView,
    AlertMarkReadView,
    PushTokenRegisterView,
    PushTokenUnregisterView,
)

urlpatterns = [
    path("", AlertListView.as_view(), name="alert-list"),
    path("read-all/", AlertMarkAllReadView.as_view(), name="alert-read-all"),
    path("<uuid:alert_id>/read/", AlertMarkReadView.as_view(), name="alert-read"),
    path("<uuid:alert_id>/", AlertDeleteView.as_view(), name="alert-delete"),
    path("push-tokens/", PushTokenRegisterView.as_view(), name="push-token-register"),
    path(
        "push-tokens/<uuid:token_id>/",
        PushTokenUnregisterView.as_view(),
        name="push-token-unregister",
    ),
]
