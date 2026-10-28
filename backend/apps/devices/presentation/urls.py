from django.urls import path

from apps.devices.presentation.views.device_views import (
    ConsentRevokeView,
    DeviceDetailView,
    DeviceDisconnectView,
    DeviceListView,
    OwnedDeviceListView,
    OwnedDevicePauseView,
    OwnedDeviceResumeView,
    OwnedDeviceStatusView,
    PairingCompleteView,
    PairingInitiateView,
)
from apps.devices.presentation.views.keyword_views import (
    KeywordDetailView,
    KeywordListCreateView,
)
from apps.devices.presentation.views.screen_share_views import (
    OwnedScreenSharePendingView,
    ScreenShareDenyView,
    ScreenShareEndView,
    ScreenShareRequestView,
    ScreenShareStartView,
    ScreenShareStatusView,
)
from apps.devices.presentation.views.live_media_views import (
    LiveMediaEndView,
    LiveMediaFacingView,
    LiveMediaRequestView,
    LiveMediaStartView,
    LiveMediaStatusView,
    OwnedLiveMediaPendingView,
)
from apps.devices.presentation.views.safe_zone_views import (
    SafeZoneDetailView,
    SafeZoneListCreateView,
)

urlpatterns = [
    path("", DeviceListView.as_view(), name="device-list"),
    path("owned/", OwnedDeviceListView.as_view(), name="device-owned-list"),
    path(
        "owned/<uuid:device_id>/status/",
        OwnedDeviceStatusView.as_view(),
        name="device-owned-status",
    ),
    path(
        "owned/<uuid:device_id>/pause/",
        OwnedDevicePauseView.as_view(),
        name="device-owned-pause",
    ),
    path(
        "owned/<uuid:device_id>/resume/",
        OwnedDeviceResumeView.as_view(),
        name="device-owned-resume",
    ),
    path("safe-zones/", SafeZoneListCreateView.as_view(), name="safe-zone-list"),
    path(
        "safe-zones/<uuid:zone_id>/",
        SafeZoneDetailView.as_view(),
        name="safe-zone-detail",
    ),
    path("keywords/", KeywordListCreateView.as_view(), name="keyword-list"),
    path(
        "keywords/<uuid:keyword_id>/",
        KeywordDetailView.as_view(),
        name="keyword-detail",
    ),
    path("pair/initiate/", PairingInitiateView.as_view(), name="device-pair-initiate"),
    path("pair/complete/", PairingCompleteView.as_view(), name="device-pair-complete"),
    path(
        "<uuid:device_id>/screen/request/",
        ScreenShareRequestView.as_view(),
        name="device-screen-request",
    ),
    path(
        "owned/<uuid:device_id>/screen/pending/",
        OwnedScreenSharePendingView.as_view(),
        name="device-screen-pending",
    ),
    path(
        "screen/<uuid:session_id>/start/",
        ScreenShareStartView.as_view(),
        name="device-screen-start",
    ),
    path(
        "screen/<uuid:session_id>/deny/",
        ScreenShareDenyView.as_view(),
        name="device-screen-deny",
    ),
    path(
        "screen/<uuid:session_id>/end/",
        ScreenShareEndView.as_view(),
        name="device-screen-end",
    ),
    path(
        "screen/<uuid:session_id>/",
        ScreenShareStatusView.as_view(),
        name="device-screen-status",
    ),
    path(
        "<uuid:device_id>/media/request/",
        LiveMediaRequestView.as_view(),
        name="device-media-request",
    ),
    path(
        "owned/<uuid:device_id>/media/pending/",
        OwnedLiveMediaPendingView.as_view(),
        name="device-media-pending",
    ),
    path(
        "media/<uuid:session_id>/start/",
        LiveMediaStartView.as_view(),
        name="device-media-start",
    ),
    path(
        "media/<uuid:session_id>/facing/",
        LiveMediaFacingView.as_view(),
        name="device-media-facing",
    ),
    path(
        "media/<uuid:session_id>/end/",
        LiveMediaEndView.as_view(),
        name="device-media-end",
    ),
    path(
        "media/<uuid:session_id>/",
        LiveMediaStatusView.as_view(),
        name="device-media-status",
    ),
    path("<uuid:device_id>/", DeviceDetailView.as_view(), name="device-detail"),
    path("<uuid:device_id>/disconnect/", DeviceDisconnectView.as_view(), name="device-disconnect"),
    path("<uuid:device_id>/consent/", ConsentRevokeView.as_view(), name="device-consent-revoke"),
]
