"""Merged, time-ordered activity feed across a device's event types + alerts.

Read-only aggregation used by the monitor-side Activity timeline. It fans in
DeviceEvent rows and Alert rows for a single device, applies an optional
category filter and [from, to] window, and returns one reverse-chronological
page.

Pagination is a bounded offset cursor: because the merged stream is ordered by
timestamp desc, the first ``offset + limit`` merged items can come from at most
``offset + limit + 1`` rows of each source, so every source query stays bounded
(kind to the low-RAM TX6 — no full-table scans, no giant in-memory merges).
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Any

from django.utils.dateparse import parse_datetime

from apps.alerts.infrastructure.models.alert import Alert
from apps.devices.infrastructure.models.device import Device
from apps.events.infrastructure.models.event import DeviceEvent
from core.crypto.field_encryption import decrypt_payload
from core.domain.exceptions import ValidationError

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_OFFSET = 5000

# Category -> the event_type prefixes that belong to it. "alerts" is special and
# pulls from the Alert table instead of DeviceEvent.
CATEGORY_EVENT_PREFIXES: dict[str, tuple[str, ...]] = {
    "location": ("location.", "geofence."),
    "app_inventory": ("app_inventory.",),
    "notifications": ("notification.",),
    "app_usage": ("app_usage.",),
    "telemetry": ("device.",),
    "contacts": ("contact.",),
    "calls": ("call.",),
    "sms": ("sms.",),
    "messages": ("message.",),
}
ALERTS_CATEGORY = "alerts"
VALID_CATEGORIES = frozenset(CATEGORY_EVENT_PREFIXES) | {ALERTS_CATEGORY}


class ActivityFeedService:
    def parse_limit(self, raw: str | None) -> int:
        if not raw:
            return DEFAULT_LIMIT
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError("limit must be an integer") from exc
        return max(1, min(value, MAX_LIMIT))

    def parse_range(
        self, frm: str | None, to: str | None
    ) -> tuple[datetime | None, datetime | None]:
        start = parse_datetime(frm) if frm else None
        end = parse_datetime(to) if to else None
        if frm and start is None:
            raise ValidationError("from must be ISO-8601")
        if to and end is None:
            raise ValidationError("to must be ISO-8601")
        return start, end

    def parse_categories(self, raw: str | None) -> list[str]:
        if not raw:
            return sorted(VALID_CATEGORIES)
        cats = [c.strip() for c in raw.split(",") if c.strip()]
        bad = set(cats) - VALID_CATEGORIES
        if bad:
            raise ValidationError(
                f"Unknown types: {', '.join(sorted(bad))}. "
                f"Valid: {', '.join(sorted(VALID_CATEGORIES))}"
            )
        return cats

    def decode_cursor(self, raw: str | None) -> int:
        if not raw:
            return 0
        try:
            value = int(base64.urlsafe_b64decode(raw.encode()).decode())
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise ValidationError("Invalid cursor") from exc
        if value < 0 or value > MAX_OFFSET:
            raise ValidationError("Invalid cursor")
        return value

    def encode_cursor(self, offset: int) -> str:
        return base64.urlsafe_b64encode(str(offset).encode()).decode()

    def build_page(
        self,
        *,
        device: Device,
        categories: list[str],
        start: datetime | None,
        end: datetime | None,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        bound = offset + limit + 1
        items: list[dict[str, Any]] = []

        event_prefixes = self._event_prefixes(categories)
        if event_prefixes:
            items.extend(
                self._event_items(
                    device=device,
                    prefixes=event_prefixes,
                    start=start,
                    end=end,
                    bound=bound,
                )
            )
        if ALERTS_CATEGORY in categories:
            items.extend(
                self._alert_items(
                    device=device, start=start, end=end, bound=bound
                )
            )

        items.sort(key=lambda item: item["_sort"], reverse=True)
        window = items[offset : offset + limit]
        for item in window:
            item.pop("_sort", None)
        has_next = len(items) > offset + limit
        next_cursor = self.encode_cursor(offset + limit) if has_next else None
        return {
            "device_id": str(device.id),
            "results": window,
            "next": next_cursor,
        }

    def _event_prefixes(self, categories: list[str]) -> list[str]:
        prefixes: list[str] = []
        for cat in categories:
            prefixes.extend(CATEGORY_EVENT_PREFIXES.get(cat, ()))
        return prefixes

    def _category_for_event_type(self, event_type: str) -> str:
        for cat, prefixes in CATEGORY_EVENT_PREFIXES.items():
            if event_type.startswith(prefixes):
                return cat
        return "other"

    def _event_items(
        self,
        *,
        device: Device,
        prefixes: list[str],
        start: datetime | None,
        end: datetime | None,
        bound: int,
    ) -> list[dict[str, Any]]:
        from django.db.models import Q

        prefix_q = Q()
        for prefix in prefixes:
            prefix_q |= Q(event_type__startswith=prefix)
        qs = DeviceEvent.objects.filter(device=device).filter(prefix_q)
        if start:
            qs = qs.filter(event_timestamp__gte=start)
        if end:
            qs = qs.filter(event_timestamp__lte=end)
        qs = qs.order_by("-event_timestamp", "-created_at")[:bound]

        items: list[dict[str, Any]] = []
        for event in qs:
            items.append(
                {
                    "_sort": event.event_timestamp,
                    "source": "event",
                    "id": str(event.id),
                    "category": self._category_for_event_type(event.event_type),
                    "event_type": event.event_type,
                    "timestamp": event.event_timestamp.isoformat(),
                    "title": "",
                    "body": "",
                    "severity": None,
                    "payload": decrypt_payload(event.payload or {}),
                }
            )
        return items

    def _alert_items(
        self,
        *,
        device: Device,
        start: datetime | None,
        end: datetime | None,
        bound: int,
    ) -> list[dict[str, Any]]:
        qs = Alert.objects.filter(device=device)
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lte=end)
        qs = qs.order_by("-created_at")[:bound]

        items: list[dict[str, Any]] = []
        for alert in qs:
            items.append(
                {
                    "_sort": alert.created_at,
                    "source": "alert",
                    "id": str(alert.id),
                    "category": ALERTS_CATEGORY,
                    "event_type": alert.type,
                    "timestamp": alert.created_at.isoformat(),
                    "title": alert.title,
                    "body": alert.body,
                    "severity": alert.severity,
                    "payload": alert.metadata or {},
                }
            )
        return items
