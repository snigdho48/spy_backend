from django.urls import re_path

from apps.devices.presentation.consumers.media_consumer import LiveMediaConsumer
from apps.devices.presentation.consumers.screen_consumer import ScreenShareConsumer
from apps.events.presentation.consumers.event_consumer import EventStreamConsumer

websocket_urlpatterns = [
    re_path(r"ws/v1/events/$", EventStreamConsumer.as_asgi()),
    re_path(
        r"ws/v1/screen/(?P<session_id>[0-9a-fA-F-]+)/$",
        ScreenShareConsumer.as_asgi(),
    ),
    re_path(
        r"ws/v1/media/(?P<session_id>[0-9a-fA-F-]+)/$",
        LiveMediaConsumer.as_asgi(),
    ),
]
