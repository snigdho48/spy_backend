from django.urls import path

from apps.events.presentation.views.event_views import EventIngestView, EventListView

urlpatterns = [
    path("", EventListView.as_view(), name="event-list"),
    path("batch/", EventIngestView.as_view(), name="event-ingest"),
]
