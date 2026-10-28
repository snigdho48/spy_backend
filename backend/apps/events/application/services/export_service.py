"""Stream CSV / PDF exports of a device's consented feeds.

Designed for the low-RAM TX6: CSV uses stdlib csv + StreamingHttpResponse;
PDF is built with reportlab in a single pass over an iterator (no giant
in-memory buffers of decoded payloads).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.infrastructure.models.user import User
from apps.alerts.infrastructure.models.alert import Alert
from apps.devices.application.services.device_access import DeviceAccessService
from apps.devices.infrastructure.models.device import Device
from apps.events.infrastructure.models.event import DeviceEvent
from apps.tenants.infrastructure.models.tenant import Tenant
from core.crypto.field_encryption import decrypt_payload
from core.domain.exceptions import ValidationError

VALID_FEEDS = frozenset({"events", "locations", "app_usage", "alerts", "telemetry"})
LOCATION_PREFIX = "location."
APP_USAGE_TYPE = "app_usage.snapshot"
TELEMETRY_TYPE = "device.telemetry"


class Echo:
    """File-like object that returns whatever is written (for csv streaming)."""

    def write(self, value: str) -> str:
        return value


class DeviceExportService:
    def resolve_device(
        self, *, user: User, tenant: Tenant, device_id
    ) -> Device:
        return DeviceAccessService().get_accessible_device(
            user=user, tenant=tenant, device_id=device_id
        )

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

    def parse_feeds(self, raw: str | None) -> list[str]:
        if not raw:
            return ["events", "locations", "app_usage", "alerts"]
        feeds = [f.strip() for f in raw.split(",") if f.strip()]
        bad = set(feeds) - VALID_FEEDS
        if bad:
            raise ValidationError(
                f"Unknown feeds: {', '.join(sorted(bad))}. "
                f"Valid: {', '.join(sorted(VALID_FEEDS))}"
            )
        return feeds

    def iter_events(
        self,
        *,
        device: Device,
        start: datetime | None,
        end: datetime | None,
        event_type: str | None = None,
        event_prefix: str | None = None,
    ) -> Iterator[DeviceEvent]:
        qs = DeviceEvent.objects.filter(device=device).order_by("event_timestamp")
        if start:
            qs = qs.filter(event_timestamp__gte=start)
        if end:
            qs = qs.filter(event_timestamp__lte=end)
        if event_type:
            qs = qs.filter(event_type=event_type)
        if event_prefix:
            qs = qs.filter(event_type__startswith=event_prefix)
        return qs.iterator(chunk_size=200)

    def iter_alerts(
        self,
        *,
        device: Device,
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[Alert]:
        qs = Alert.objects.filter(device=device).order_by("created_at")
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lte=end)
        return qs.iterator(chunk_size=200)

    def stream_csv(
        self,
        *,
        device: Device,
        feeds: list[str],
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[str]:
        writer = csv.writer(Echo())
        yield writer.writerow(
            ["feed", "timestamp", "type", "title", "body", "payload_json"]
        )
        if "events" in feeds:
            for event in self.iter_events(device=device, start=start, end=end):
                yield writer.writerow(
                    [
                        "events",
                        event.event_timestamp.isoformat(),
                        event.event_type,
                        "",
                        "",
                        _payload_json(event.payload),
                    ]
                )
        if "locations" in feeds:
            for event in self.iter_events(
                device=device,
                start=start,
                end=end,
                event_prefix=LOCATION_PREFIX,
            ):
                yield writer.writerow(
                    [
                        "locations",
                        event.event_timestamp.isoformat(),
                        event.event_type,
                        "",
                        "",
                        _payload_json(event.payload),
                    ]
                )
        if "app_usage" in feeds:
            for event in self.iter_events(
                device=device,
                start=start,
                end=end,
                event_type=APP_USAGE_TYPE,
            ):
                yield writer.writerow(
                    [
                        "app_usage",
                        event.event_timestamp.isoformat(),
                        event.event_type,
                        "",
                        "",
                        _payload_json(event.payload),
                    ]
                )
        if "telemetry" in feeds:
            for event in self.iter_events(
                device=device,
                start=start,
                end=end,
                event_type=TELEMETRY_TYPE,
            ):
                yield writer.writerow(
                    [
                        "telemetry",
                        event.event_timestamp.isoformat(),
                        event.event_type,
                        "",
                        "",
                        _payload_json(event.payload),
                    ]
                )
        if "alerts" in feeds:
            for alert in self.iter_alerts(device=device, start=start, end=end):
                yield writer.writerow(
                    [
                        "alerts",
                        alert.created_at.isoformat(),
                        alert.type,
                        alert.title,
                        alert.body,
                        _payload_json(alert.metadata),
                    ]
                )

    def build_pdf_bytes(
        self,
        *,
        device: Device,
        feeds: list[str],
        start: datetime | None,
        end: datetime | None,
    ) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4
        y = height - 40
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, y, f"Device export: {device.name}")
        y -= 18
        c.setFont("Helvetica", 9)
        c.drawString(
            40,
            y,
            f"Generated {timezone.now().isoformat()} | feeds={','.join(feeds)}",
        )
        y -= 14
        c.drawString(
            40,
            y,
            f"Range: {start.isoformat() if start else '…'} → "
            f"{end.isoformat() if end else '…'}",
        )
        y -= 24

        def writeln(text: str, *, bold: bool = False) -> None:
            nonlocal y
            if y < 50:
                c.showPage()
                y = height - 40
                c.setFont("Helvetica", 9)
            c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
            # Truncate long lines so they fit the page.
            c.drawString(40, y, text[:110])
            y -= 12

        if "events" in feeds:
            writeln("Events", bold=True)
            for event in self.iter_events(device=device, start=start, end=end):
                writeln(
                    f"{event.event_timestamp.isoformat()}  {event.event_type}"
                )
            y -= 6
        if "locations" in feeds:
            writeln("Locations", bold=True)
            for event in self.iter_events(
                device=device,
                start=start,
                end=end,
                event_prefix=LOCATION_PREFIX,
            ):
                payload = decrypt_payload(event.payload or {})
                writeln(
                    f"{event.event_timestamp.isoformat()}  "
                    f"lat={payload.get('lat')} lng={payload.get('lng')}"
                )
            y -= 6
        if "app_usage" in feeds:
            writeln("App usage", bold=True)
            for event in self.iter_events(
                device=device,
                start=start,
                end=end,
                event_type=APP_USAGE_TYPE,
            ):
                apps = (event.payload or {}).get("apps") or []
                writeln(
                    f"{event.event_timestamp.isoformat()}  apps={len(apps)}"
                )
            y -= 6
        if "telemetry" in feeds:
            writeln("Telemetry", bold=True)
            for event in self.iter_events(
                device=device,
                start=start,
                end=end,
                event_type=TELEMETRY_TYPE,
            ):
                p = event.payload or {}
                writeln(
                    f"{event.event_timestamp.isoformat()}  "
                    f"battery={p.get('battery_pct')} charging={p.get('charging')}"
                )
            y -= 6
        if "alerts" in feeds:
            writeln("Alerts", bold=True)
            for alert in self.iter_alerts(device=device, start=start, end=end):
                writeln(
                    f"{alert.created_at.isoformat()}  [{alert.severity}] "
                    f"{alert.type}: {alert.title}"
                )

        c.save()
        return buf.getvalue()


def _payload_json(payload: Any) -> str:
    import json

    try:
        return json.dumps(decrypt_payload(payload or {}), default=str)
    except Exception:
        return "{}"
