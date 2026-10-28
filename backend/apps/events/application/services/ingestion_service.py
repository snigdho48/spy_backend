import threading

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from apps.accounts.infrastructure.models.user import User
from apps.devices.application.services.pairing_service import ConsentService
from apps.devices.application.services.safe_zone_service import SafeZoneService
from apps.devices.application.services.sharing_pause_service import SharingPauseService
from apps.devices.infrastructure.models.device import Device
from apps.events.application.services.contact_payload import (
    CONTACT_EVENT_PREFIXES,
    apply_contact_redaction,
)
from apps.events.domain.event_types import (
    APP_INVENTORY_TYPES,
    CONTACT_SNAPSHOT_TYPES,
)
from apps.events.infrastructure.models.event import DeviceEvent
from apps.events.infrastructure.models.snapshots import (
    DeviceAppInventorySnapshot,
    DeviceAppUsageSnapshot,
    DeviceContactSnapshot,
    DeviceTelemetrySnapshot,
)
from apps.tenants.infrastructure.models.tenant import Tenant
from core.domain.exceptions import ConflictError, EntityNotFoundError, ValidationError

_LOCATIONISH_PREFIXES = ("location.", "geofence.")


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value):
    if value is None:
        return None
    return bool(value)


def _as_dt(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            return timezone.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value


class EventIngestionService:
    def ingest_batch(
        self,
        *,
        user: User,
        device_id,
        events: list[dict],
    ) -> dict:
        device = (
            Device.objects.filter(
                pk=device_id,
                owner=user,
                status=Device.Status.ACTIVE,
            )
            .select_related("tenant")
            .first()
        )
        if not device:
            raise EntityNotFoundError("Active device not found for this account")

        pause_service = SharingPauseService()
        active_pause = pause_service.get_active_pause(device)
        if active_pause:
            return {
                "accepted": 0,
                "rejected": len(events),
                "errors": [
                    {
                        "index": idx,
                        "message": "Sharing paused; telemetry not accepted",
                    }
                    for idx in range(len(events))
                ],
                "paused": True,
                "paused_until": active_pause.expires_at,
            }

        tenant = device.tenant

        consent_service = ConsentService()
        active_consent = consent_service.get_active_consent(device)

        idempotency_keys = [
            e["idempotency_key"]
            for e in events
            if e.get("idempotency_key")
        ]
        existing_idempotency_keys: set[str] = set()
        if idempotency_keys:
            existing_idempotency_keys = set(
                DeviceEvent.objects.filter(
                    idempotency_key__in=idempotency_keys
                ).values_list("idempotency_key", flat=True)
            )

        accepted = 0
        rejected = 0
        errors: list[dict] = []
        created_events: list[DeviceEvent] = []

        for idx, event_data in enumerate(events):
            try:
                event_type = event_data.get("event_type", "")
                if not event_type:
                    raise ValidationError("event_type is required")

                consent_service.validate_event_scope(
                    device, event_type, consent=active_consent
                )

                idempotency_key = event_data.get("idempotency_key")
                if idempotency_key and idempotency_key in existing_idempotency_keys:
                    raise ConflictError("Duplicate idempotency key")

                event_timestamp = event_data.get("timestamp")
                if event_timestamp:
                    if isinstance(event_timestamp, str):
                        event_timestamp = timezone.datetime.fromisoformat(
                            event_timestamp.replace("Z", "+00:00")
                        )
                else:
                    event_timestamp = timezone.now()

                if pause_service.covers_timestamp(device, event_timestamp):
                    raise ValidationError(
                        "Event timestamp falls inside a sharing pause window"
                    )

                payload = dict(event_data.get("payload") or {})
                if event_type.startswith(_LOCATIONISH_PREFIXES):
                    # Geofence enter/exit require a known zone; location may
                    # optionally reference one. No third-party reverse geocode.
                    if event_type.startswith("geofence.") or payload.get(
                        "zone_id"
                    ) or payload.get("zone_name"):
                        payload = SafeZoneService().enrich_location_payload(
                            device, payload
                        )
                elif event_type.startswith(CONTACT_EVENT_PREFIXES):
                    # call.* / sms.* contact metadata. Do not fetch photos (SSRF).
                    payload = apply_contact_redaction(payload)

                from core.crypto.field_encryption import encrypt_payload

                payload = encrypt_payload(payload)

                created_events.append(
                    DeviceEvent(
                        tenant=tenant,
                        device=device,
                        event_type=event_type,
                        payload=payload,
                        idempotency_key=idempotency_key,
                        event_timestamp=event_timestamp,
                    )
                )
                accepted += 1
            except Exception as exc:
                rejected += 1
                errors.append({"index": idx, "message": str(exc)})

        if created_events:
            with transaction.atomic():
                DeviceEvent.objects.bulk_create(created_events, ignore_conflicts=True)
                device.last_seen_at = timezone.now()
                device.save(update_fields=["last_seen_at", "updated_at"])
                self._upsert_snapshots(tenant, device, created_events)

            # Alert hooks + push enqueue run after commit so Celery never races.
            self._run_alert_hooks(device, created_events)

            events_snapshot = list(created_events)
            threading.Thread(
                target=self._broadcast_events,
                args=(tenant, device, events_snapshot),
                daemon=True,
            ).start()

        return {"accepted": accepted, "rejected": rejected, "errors": errors}

    def _upsert_snapshots(
        self,
        tenant: Tenant,
        device: Device,
        events: list[DeviceEvent],
    ) -> None:
        """Keep latest contact / app-inventory snapshot rows in sync with ingest."""
        for event in events:
            if (
                event.event_type in CONTACT_SNAPSHOT_TYPES
                or event.event_type.startswith("contact.")
            ):
                from core.crypto.field_encryption import encrypt_contacts

                contacts = event.payload.get("contacts") or []
                if not isinstance(contacts, list):
                    contacts = []
                # Payload may already be field-encrypted; encrypt_contacts is
                # idempotent for enc:v1: values.
                contacts = encrypt_contacts(contacts)
                DeviceContactSnapshot.objects.update_or_create(
                    device=device,
                    defaults={
                        "tenant": tenant,
                        "contacts": contacts,
                        "contact_count": len(contacts),
                        "source_event_id": event.pk,
                        "captured_at": event.event_timestamp,
                    },
                )
            elif (
                event.event_type in APP_INVENTORY_TYPES
                or event.event_type.startswith("app_inventory.")
            ):
                apps = event.payload.get("apps") or []
                if not isinstance(apps, list):
                    apps = []
                DeviceAppInventorySnapshot.objects.update_or_create(
                    device=device,
                    defaults={
                        "tenant": tenant,
                        "apps": apps,
                        "app_count": len(apps),
                        "include_system": bool(
                            event.payload.get("include_system", True)
                        ),
                        "source_event_id": event.pk,
                        "captured_at": event.event_timestamp,
                    },
                )
            elif event.event_type == "app_usage.snapshot" or event.event_type.startswith(
                "app_usage."
            ):
                usage_apps = event.payload.get("apps") or []
                if not isinstance(usage_apps, list):
                    usage_apps = []
                DeviceAppUsageSnapshot.objects.update_or_create(
                    device=device,
                    defaults={
                        "tenant": tenant,
                        "apps": usage_apps,
                        "app_count": len(usage_apps),
                        "period_start": _as_dt(event.payload.get("period_start")),
                        "period_end": _as_dt(event.payload.get("period_end")),
                        "source_event_id": event.pk,
                        "captured_at": event.event_timestamp,
                    },
                )
            elif event.event_type == "device.telemetry":
                payload = event.payload or {}
                DeviceTelemetrySnapshot.objects.update_or_create(
                    device=device,
                    defaults={
                        "tenant": tenant,
                        "battery_pct": _as_int(payload.get("battery_pct")),
                        "charging": _as_bool(payload.get("charging")),
                        "network_type": str(payload.get("network_type") or "")[:32],
                        "storage_free": _as_int(payload.get("storage_free")),
                        "storage_total": _as_int(payload.get("storage_total")),
                        "ram_free": _as_int(payload.get("ram_free")),
                        "ram_total": _as_int(payload.get("ram_total")),
                        "metrics": payload if isinstance(payload, dict) else {},
                        "source_event_id": event.pk,
                        "captured_at": event.event_timestamp,
                    },
                )


    def _run_alert_hooks(self, device: Device, events: list[DeviceEvent]) -> None:
        """Generate alerts from newly ingested events. Failures must not roll back ingest."""
        try:
            from apps.alerts.application.services.alert_service import AlertService
            from apps.devices.application.services.geofence_service import GeofenceService
            from django.conf import settings as dj_settings

            alerts = AlertService()
            geo = GeofenceService()
            for event in events:
                et = event.event_type
                payload = event.payload or {}
                if et.startswith("location."):
                    lat = payload.get("lat", payload.get("latitude"))
                    lng = payload.get("lng", payload.get("longitude"))
                    try:
                        lat_f = float(lat)
                        lng_f = float(lng)
                    except (TypeError, ValueError):
                        continue
                    for change in geo.evaluate_location(
                        device=device, lat=lat_f, lng=lng_f, at=event.event_timestamp
                    ):
                        alerts.on_geofence_transition(
                            device=device,
                            zone=change["zone"],
                            transition=change["transition"],
                            distance_m=change["distance_m"],
                        )
                elif et == "app_inventory.snapshot" or et.startswith("app_inventory."):
                    self._diff_app_inventory(device, event, payload, alerts)
                elif et == "sim.changed":
                    alerts.on_sim_changed(device=device, payload=payload)
                elif et == "device.telemetry":
                    try:
                        pct = int(payload.get("battery_pct"))
                    except (TypeError, ValueError):
                        continue
                    charging = bool(payload.get("charging"))
                    threshold = int(
                        getattr(dj_settings, "LOW_BATTERY_THRESHOLD_PCT", 15)
                    )
                    if pct <= threshold and not charging:
                        alerts.on_low_battery(
                            device=device, battery_pct=pct, charging=charging
                        )
                elif et == "sos.triggered":
                    alerts.on_sos(device=device, payload=payload)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Alert hooks failed for device %s", device.id
            )

    def _diff_app_inventory(self, device, current_event, payload, alerts) -> None:
        """Emit app_installed alerts for packages not in the previous snapshot."""
        new_apps = payload.get("apps") or []
        if not isinstance(new_apps, list):
            return
        new_pkgs = {
            str(a.get("package") or "").strip()
            for a in new_apps
            if isinstance(a, dict) and a.get("package")
        }
        prev_event = (
            DeviceEvent.objects.filter(
                device=device, event_type="app_inventory.snapshot"
            )
            .exclude(pk=current_event.pk)
            .order_by("-event_timestamp")
            .first()
        )
        if prev_event is None:
            return
        old_apps = (prev_event.payload or {}).get("apps") or []
        old_pkgs = {
            str(a.get("package") or "").strip()
            for a in old_apps
            if isinstance(a, dict) and a.get("package")
        }
        added = new_pkgs - old_pkgs
        name_by_pkg = {
            str(a.get("package")): a.get("app_name") or a.get("name") or ""
            for a in new_apps
            if isinstance(a, dict) and a.get("package")
        }
        for pkg in sorted(added):
            alerts.on_app_installed(
                device=device, package=pkg, app_name=name_by_pkg.get(pkg, "")
            )

    def _broadcast_events(
        self, tenant: Tenant, device: Device, events: list[DeviceEvent]
    ) -> None:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return

        group_name = f"tenant_{tenant.id}_events"
        from core.crypto.field_encryption import decrypt_payload

        batch_payload = [
            {
                "device_id": str(device.id),
                "event_type": event.event_type,
                "payload": decrypt_payload(event.payload or {}),
                "timestamp": event.event_timestamp.isoformat(),
            }
            for event in events
        ]
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "events.batch",
                "data": batch_payload,
            },
        )
