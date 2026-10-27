import json
import uuid
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from apps.devices.infrastructure.models.device import Device

User = get_user_model()


class EventStreamConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.tenant_id = None
        self.groups: list[str] = []
        # None = deliver every tenant event (legacy behaviour until the client
        # sends a non-empty `subscribe`); otherwise a set of device id strings.
        self.device_filter: set[str] | None = None

        token = self._extract_token()
        if not token:
            await self.close(code=4001)
            return

        user = await self._authenticate(token)
        if not user:
            await self.close(code=4001)
            return

        self.user = user
        tenant_id = await self._get_tenant_id(user)
        if not tenant_id:
            await self.close(code=4003)
            return

        self.tenant_id = tenant_id
        group = f"tenant_{tenant_id}_events"
        await self.channel_layer.group_add(group, self.channel_name)
        self.groups.append(group)
        await self.accept()

    async def disconnect(self, close_code):
        for group in self.groups:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return

        if data.get("action") == "subscribe" and self.tenant_id:
            requested = data.get("device_ids", [])
            if not isinstance(requested, list):
                requested = []

            if not requested:
                # Empty subscribe = all devices in the tenant (backward compatible).
                self.device_filter = None
                await self.send(
                    text_data=json.dumps({"type": "subscribed", "device_ids": []})
                )
                return

            allowed = await self._filter_tenant_device_ids(requested)
            self.device_filter = set(allowed)
            rejected = [
                d for d in requested if str(d).lower() not in self.device_filter
            ]
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "subscribed",
                        "device_ids": allowed,
                        "rejected_device_ids": [str(d) for d in rejected],
                    }
                )
            )

    def _is_allowed(self, item: dict) -> bool:
        if self.device_filter is None:
            return True
        return str(item.get("device_id", "")).lower() in self.device_filter

    async def event_message(self, event):
        if self._is_allowed(event["data"]):
            await self.send(text_data=json.dumps({"type": "event", **event["data"]}))

    async def events_batch(self, event):
        for item in event["data"]:
            if self._is_allowed(item):
                await self.send(text_data=json.dumps({"type": "event", **item}))

    async def device_status(self, event):
        data = event["data"]
        if self._is_allowed(data):
            await self.send(
                text_data=json.dumps({"type": "device_status", **data})
            )

    def _extract_token(self) -> str | None:
        # Prefer the Authorization header; the query token remains a fallback
        # because mobile WebSocket clients cannot always set headers.
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
            # Expired, malformed, wrong type, unknown or inactive user.
            return None

    @database_sync_to_async
    def _filter_tenant_device_ids(self, requested: list) -> list[str]:
        """Return requested ids (as lowercase strings) that belong to this tenant."""
        parsed: list[uuid.UUID] = []
        for value in requested:
            try:
                parsed.append(uuid.UUID(str(value)))
            except (ValueError, AttributeError):
                continue
        if not parsed:
            return []
        found = {
            str(pk)
            for pk in Device.objects.filter(
                tenant_id=self.tenant_id, pk__in=parsed
            ).values_list("pk", flat=True)
        }
        out: list[str] = []
        for u in parsed:
            s = str(u)
            if s in found and s not in out:
                out.append(s)
        return out

    @database_sync_to_async
    def _get_tenant_id(self, user) -> str | None:
        membership = (
            user.tenant_memberships.select_related("tenant")
            .filter(tenant__is_active=True)
            .order_by("created_at")
            .first()
        )
        return str(membership.tenant_id) if membership else None
