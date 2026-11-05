"""Channels consumer for live screen-share frame relay.

Authorization (consent, pause, session open, tenant role) is checked at
connect AND re-checked on inbound frames. REST end / consent revoke / pause
also ``group_send`` a ``screen.closed`` event that kicks every socket in the
``screen_<id>`` group — so a mid-session revoke cannot keep streaming.
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

ALLOWED_FRAME_TYPES = {"screen.frame", "screen.signal"}
CONTROL_TYPE = "screen.control"

# Pragmatic publisher-side throttle: drop frames above this rate. Defence in
# depth only — the native capture layer should already cap fps.
MAX_FRAMES_PER_SECOND = 10
# Reject oversized frame payloads (base64 JPEG). ~700 KB keeps a few-fps
# downscaled stream comfortable while blocking abuse.
MAX_FRAME_BYTES = 700_000
MAX_CONTROL_PER_SECOND = 20
MAX_CONTROL_BYTES = 4096


class ScreenShareConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]
        self.group = f"screen_{self.session_id}"
        self.is_publisher = False
        self._window_start = 0.0
        self._frames_in_window = 0
        self._control_window_start = 0.0
        self._controls_in_window = 0

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
            # Not found / not permitted / closed / consent revoked / paused.
            await self.close(code=4003)
            return
        self.is_publisher = role == "publisher"

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send(
            text_data=json.dumps(
                {"type": "screen.ready", "role": role, "session_id": str(self.session_id)}
            )
        )

    async def disconnect(self, close_code):
        if getattr(self, "group", None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        msg_type = data.get("type")

        if msg_type == CONTROL_TYPE:
            await self._receive_control(text_data, data)
            return

        # Only the monitored device may publish frames / signals.
        if not self.is_publisher:
            return
        if msg_type not in ALLOWED_FRAME_TYPES:
            return
        if len(text_data) > MAX_FRAME_BYTES:
            return

        # Defence in depth: re-gate consent / pause / open on every publish.
        role = await self._session_role(self.user)
        if role != "publisher":
            await self.close(code=4003)
            return

        if msg_type == "screen.frame" and not self._allow_frame():
            return

        await self.channel_layer.group_send(
            self.group,
            {
                "type": "screen.relay",
                "payload": {
                    "type": msg_type,
                    "session_id": str(self.session_id),
                    "data": data.get("data"),
                },
                "sender": self.channel_name,
            },
        )

    async def screen_relay(self, event):
        # Publisher does not need its own frames echoed back.
        if event.get("sender") == self.channel_name:
            return
        await self.send(text_data=json.dumps(event["payload"]))

    async def screen_closed(self, event):
        """Kicked by REST end / consent revoke / pause / expire."""
        reason = event.get("reason") or "closed"
        try:
            await self.send(
                text_data=json.dumps({"type": "screen.closed", "reason": reason})
            )
        except Exception:
            pass
        await self.close(code=4003)

    async def _receive_control(self, text_data: str, data: dict) -> None:
        """Relay a viewer control intent only when the device has approved."""
        from apps.devices.application.services.screen_control import (
            validate_control_intent,
        )

        if self.is_publisher:
            return
        if len(text_data) > MAX_CONTROL_BYTES:
            await self._control_nack("invalid")
            return
        if not await self._control_allowed():
            await self._control_nack("not_approved")
            return
        if not self._allow_control():
            await self._control_nack("rate_limited")
            return
        intent = validate_control_intent(data.get("data"))
        if intent is None:
            await self._control_nack("invalid")
            return
        await self.channel_layer.group_send(
            self.group,
            {
                "type": "screen.relay",
                "payload": {
                    "type": CONTROL_TYPE,
                    "session_id": str(self.session_id),
                    "data": intent,
                },
                "sender": self.channel_name,
            },
        )

    async def _control_nack(self, reason: str) -> None:
        try:
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "screen.control_nack",
                        "session_id": str(self.session_id),
                        "reason": reason,
                    }
                )
            )
        except Exception:
            pass

    def _allow_control(self) -> bool:
        now = time.monotonic()
        if now - self._control_window_start >= 1.0:
            self._control_window_start = now
            self._controls_in_window = 0
        if self._controls_in_window >= MAX_CONTROL_PER_SECOND:
            return False
        self._controls_in_window += 1
        return True

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
        """Return 'publisher', 'viewer', or None if the connection is not allowed."""
        from apps.devices.application.services.pairing_service import ConsentService
        from apps.devices.application.services.screen_share_service import (
            MONITOR_ROLES,
            SCREEN_SCOPE,
        )
        from apps.devices.application.services.sharing_pause_service import (
            SharingPauseService,
        )
        from apps.devices.infrastructure.models.screen_share import ScreenShareSession
        from apps.tenants.infrastructure.models.membership import TenantMembership

        session = (
            ScreenShareSession.objects.filter(pk=self.session_id)
            .select_related("device", "device__tenant")
            .first()
        )
        if not session or not session.is_open:
            return None

        device = session.device
        # Consent + pause re-checked (revocable, consent-first).
        consent = ConsentService().get_active_consent(device)
        if not consent or not consent.has_scope(SCREEN_SCOPE):
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

    @database_sync_to_async
    def _control_allowed(self) -> bool:
        """Viewer may send control intents only with an explicit approved grant."""
        from apps.devices.application.services.pairing_service import ConsentService
        from apps.devices.application.services.screen_share_service import (
            MONITOR_ROLES,
            SCREEN_SCOPE,
        )
        from apps.devices.application.services.sharing_pause_service import (
            SharingPauseService,
        )
        from apps.devices.infrastructure.models.screen_share import ScreenShareSession
        from apps.tenants.infrastructure.models.membership import TenantMembership

        session = (
            ScreenShareSession.objects.filter(pk=self.session_id)
            .select_related("device", "device__tenant")
            .first()
        )
        if not session or not session.control_is_approved:
            return False

        device = session.device
        consent = ConsentService().get_active_consent(device)
        if not consent or not consent.has_scope(SCREEN_SCOPE):
            return False
        if SharingPauseService().get_active_pause(device):
            return False
        if device.owner_id == self.user.id:
            return False
        membership = TenantMembership.objects.filter(
            user=self.user, tenant_id=session.tenant_id
        ).first()
        return bool(membership and membership.role in MONITOR_ROLES)
