from django.urls import path

from apps.events.presentation.views.event_views import (
    AppInventorySnapshotLatestView,
    ContactSnapshotLatestView,
    EventIngestView,
    EventListView,
)

urlpatterns = [
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
]
