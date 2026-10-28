"""Server-side geofence evaluation against SafeZone rows.

Evaluates a device location against every enabled SafeZone that applies to
the device (tenant-wide or device-scoped). Debounces enter/exit alerts by
persisting last-known inside/outside state in GeofenceState — only a real
state change produces an alert.
"""

from __future__ import annotations

import math
from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.devices.infrastructure.models.device import Device, GeofenceState, SafeZone


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    r = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


class GeofenceService:
    def zones_for_device(self, device: Device):
        return SafeZone.objects.filter(
            tenant_id=device.tenant_id, enabled=True
        ).filter(Q(device_id__isnull=True) | Q(device_id=device.id))

    def evaluate_location(
        self,
        *,
        device: Device,
        lat: float,
        lng: float,
        at=None,
    ) -> list[dict[str, Any]]:
        """Return a list of ``{zone, transition}`` for each state change.

        ``transition`` is ``"enter"`` or ``"exit"``. No change → omitted.
        """
        at = at or timezone.now()
        transitions: list[dict[str, Any]] = []
        for zone in self.zones_for_device(device):
            distance = haversine_m(lat, lng, zone.lat, zone.lng)
            inside_now = distance <= float(zone.radius_m)
            state, created = GeofenceState.objects.get_or_create(
                device=device,
                safe_zone=zone,
                defaults={
                    "tenant_id": device.tenant_id,
                    "is_inside": inside_now,
                    "last_evaluated_at": at,
                },
            )
            if created:
                # First observation establishes the baseline; do not alert.
                continue
            if state.is_inside == inside_now:
                state.last_evaluated_at = at
                state.save(update_fields=["last_evaluated_at", "updated_at"])
                continue
            state.is_inside = inside_now
            state.last_evaluated_at = at
            state.save(
                update_fields=["is_inside", "last_evaluated_at", "updated_at"]
            )
            transitions.append(
                {
                    "zone": zone,
                    "transition": "enter" if inside_now else "exit",
                    "distance_m": round(distance, 1),
                }
            )
        return transitions
