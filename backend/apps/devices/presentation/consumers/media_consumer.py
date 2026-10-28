"""Channels consumer for live camera / microphone relay.

Authorization mirrors ScreenShareConsumer: consent scopes, pause, session open,
tenant role — checked at connect and on every publish. REST end / revoke / pause
kick the ``media_<id>`` group.
"""

from __future__ import annotations

import json
import time
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

ALLOWED_TYPES = {"media.frame", "media.audio", "media.signal"}
MAX_FRAMES_PER_SECOND = 12
MAX_PAYLOAD_BYTES = 700_000


class LiveMediaConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.group = f"media_{self.session_id}"
        self.is_publisher = False
        self._window_start = 0.0
        self._frames_in_window = 0

        token = self._extract_token()
        if not token:
            await self.close(code=4001)
            return
        user = await self._authenticate(token)
        if not user:
            await self.close(code=4001)
            return
        self.user = user

        role = await self._session_role(user)
        if role is None:
            await self.close(code=4003)
            return
        self.is_publisher = role == "publisher"

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send(
            text_data=json.dumps(
                {
                    "type": "media.ready",
                    "role": role,
                    "session_id": str(self.session_id),
                }
            )
        )

    async def disconnect(self, close_code):
        if getattr(self, "group", None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not self.is_publisher or not text_data:
            return
        if len(text_data) > MAX_PAYLOAD_BYTES:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        msg_type = data.get("type")
        if msg_type not in ALLOWED_TYPES:
            return

        role = await self._session_role(self.user)
        if role != "publisher":
            await self.close(code=4003)
            return

        if msg_type in ("media.frame", "media.audio") and not self._allow_frame():
            return

        await self.channel_layer.group_send(
            self.group,
            {
                "type": "media.relay",
                "payload": {
                    "type": msg_type,
                    "session_id": str(self.session_id),
                    "data": data.get("data"),
                },
                "sender": self.channel_name,
            },
        )

    async def media_relay(self, event):
        if event.get("sender") == self.channel_name:
            return
        await self.send(text_data=json.dumps(event["payload"]))

    async def media_closed(self, event):
        reason = event.get("reason") or "closed"
        try:
            await self.send(
                text_data=json.dumps({"type": "media.closed", "reason": reason})
            )
        except Exception:
            pass
        await self.close(code=4003)

    def _allow_frame(self) -> bool:
        now = time.monotonic()
        if now - self._window_start >= 1.0:
            self._window_start = now
            self._frames_in_window = 0
        if self._frames_in_window >= MAX_FRAMES_PER_SECOND:
            return False
        self._frames_in_window += 1
        return True

    def _extract_token(self) -> str | None:
        headers = dict(self.scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode()
        if auth.startswith("Bearer ") and auth[7:].strip():
            return auth[7:].strip()
        query = parse_qs(self.scope.get("query_string", b"").decode())
        tokens = query.get("token", [])
        if tokens and tokens[0]:
            return tokens[0]
        return None

    @database_sync_to_async
    def _authenticate(self, token: str):
        auth = JWTAuthentication()
        try:
            validated = auth.get_validated_token(token)
            return auth.get_user(validated)
        except (InvalidToken, TokenError, AuthenticationFailed):
            return None

    @database_sync_to_async
    def _session_role(self, user) -> str | None:
        from apps.devices.application.services.live_media_service import (
            MONITOR_ROLES,
            SCOPE_FOR_KIND,
            LiveMediaService,
        )
        from apps.devices.application.services.pairing_service import ConsentService
        from apps.devices.application.services.sharing_pause_service import (
            SharingPauseService,
        )
        from apps.devices.infrastructure.models.live_media import LiveMediaSession
        from apps.tenants.infrastructure.models.membership import TenantMembership

        session = (
            LiveMediaSession.objects.filter(pk=self.session_id)
            .select_related("device", "device__tenant")
            .first()
        )
        if not session or not session.is_open:
            return None

        device = session.device
        consent = ConsentService().get_active_consent(device)
        needed = SCOPE_FOR_KIND.get(session.media_kind, frozenset())
        if not consent or not needed.issubset(set(consent.scopes or [])):
            return None
        if SharingPauseService().get_active_pause(device):
            return None

        if device.owner_id == user.id:
            return "publisher"
        membership = TenantMembership.objects.filter(
            user=user, tenant_id=session.tenant_id
        ).first()
        if membership and membership.role in MONITOR_ROLES:
            return "viewer"
        return None
