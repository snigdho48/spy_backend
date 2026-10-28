from django.urls import path

from apps.events.presentation.views.event_views import (
    AppInventorySnapshotLatestView,
    AppUsageLatestView,
    AppUsageRangeView,
    ContactSnapshotLatestView,
    DeviceExportView,
    EventIngestView,
    EventListView,
    TelemetryHistoryView,
    TelemetryLatestView,
)

urlpatterns = [
    path(
        "export/",
        DeviceExportView.as_view(),
        name="event-export",
    ),
    path("", EventListView.as_view(), name="event-list"),
    path("batch/", EventIngestView.as_view(), name="event-ingest"),
    path(
        "contacts/latest/",
        ContactSnapshotLatestView.as_view(),
        name="event-contacts-latest",
    ),
    path(
        "app-inventory/latest/",
        AppInventorySnapshotLatestView.as_view(),
        name="event-app-inventory-latest",
    ),
    path(
        "app-usage/latest/",
        AppUsageLatestView.as_view(),
        name="event-app-usage-latest",
    ),
    path(
        "app-usage/",
        AppUsageRangeView.as_view(),
        name="event-app-usage-range",
    ),
    path(
        "telemetry/latest/",
        TelemetryLatestView.as_view(),
        name="event-telemetry-latest",
    ),
    path(
        "telemetry/",
        TelemetryHistoryView.as_view(),
        name="event-telemetry-history",
    ),
]
