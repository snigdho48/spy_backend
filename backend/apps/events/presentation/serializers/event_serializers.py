from rest_framework import serializers

from apps.events.application.services.contact_payload import (
    CONTACT_BOOL_FIELDS,
    CONTACT_EVENT_PREFIXES,
    MAX_CONTACT_NAME,
    apply_contact_redaction,
    normalize_https_photo_url,
    strip_control_chars,
)
from apps.events.application.services.snapshot_payloads import (
    normalize_event_payload,
)
from apps.events.domain.event_types import (
    APP_INVENTORY_TYPES,
    CONTACT_SNAPSHOT_TYPES,
    EventTypes,
    NOTIFICATION_FEED_TYPES,
    RICH_MESSAGE_TYPES,
)
from apps.events.infrastructure.models.event import DeviceEvent
from apps.events.infrastructure.models.snapshots import (
    DeviceAppInventorySnapshot,
    DeviceContactSnapshot,
)

MAX_PLACE_NAME = 128
MAX_ADDRESS = 255
MAX_ZONE_NAME = 160

LOCATION_EVENT_TYPES = frozenset(
    {
        "location.update",
        "location.snapshot",
    }
)
GEOFENCE_EVENT_TYPES = frozenset(
    {
        "geofence.enter",
        "geofence.exit",
    }
)

# Known keys; extras are allowed for older clients but string lengths are capped
# when keys match.
LOCATION_STRING_LIMITS = {
    "place_name": MAX_PLACE_NAME,
    "address": MAX_ADDRESS,
    "zone_name": MAX_ZONE_NAME,
    "label": MAX_PLACE_NAME,
    "name": MAX_PLACE_NAME,
}


class EventItemSerializer(serializers.Serializer):
    event_type = serializers.CharField(max_length=64)
    payload = serializers.DictField(required=False, default=dict)
    idempotency_key = serializers.CharField(max_length=128, required=False)
    timestamp = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        event_type = attrs["event_type"]
        payload = attrs.get("payload") or {}
        if not isinstance(payload, dict):
            raise serializers.ValidationError({"payload": "Must be an object"})

        if event_type in LOCATION_EVENT_TYPES or event_type in GEOFENCE_EVENT_TYPES:
            attrs["payload"] = self._validate_locationish_payload(
                event_type, payload
            )
        elif event_type.startswith(CONTACT_EVENT_PREFIXES):
            # call.* / sms.* contact metadata (not address-book contact.*)
            attrs["payload"] = self._validate_contact_payload(payload)
        elif (
            event_type in CONTACT_SNAPSHOT_TYPES
            or event_type.startswith("contact.")
            or event_type in APP_INVENTORY_TYPES
            or event_type.startswith("app_inventory.")
            or event_type in RICH_MESSAGE_TYPES
            or event_type in NOTIFICATION_FEED_TYPES
            or event_type.startswith("notification.")
            or event_type == EventTypes.MESSAGE_NOTIFICATION
        ):
            try:
                attrs["payload"] = normalize_event_payload(event_type, payload)
            except ValueError as exc:
                raise serializers.ValidationError({"payload": str(exc)}) from exc
        return attrs

    def _validate_locationish_payload(self, event_type: str, payload: dict) -> dict:
        out = dict(payload)

        for key, max_len in LOCATION_STRING_LIMITS.items():
            if key not in out or out[key] is None:
                continue
            value = out[key]
            if not isinstance(value, str):
                raise serializers.ValidationError(
                    {f"payload.{key}": "Must be a string"}
                )
            if len(value) > max_len:
                raise serializers.ValidationError(
                    {f"payload.{key}": f"Cannot exceed {max_len} characters"}
                )

        if "zone_id" in out and out["zone_id"] is not None:
            zone_id = out["zone_id"]
            if not isinstance(zone_id, str) or not zone_id.strip():
                raise serializers.ValidationError(
                    {"payload.zone_id": "Must be a non-empty string UUID"}
                )

        for coord in ("lat", "lng"):
            if coord in out and out[coord] is not None:
                try:
                    float(out[coord])
                except (TypeError, ValueError) as exc:
                    raise serializers.ValidationError(
                        {f"payload.{coord}": "Must be a number"}
                    ) from exc

        if event_type in GEOFENCE_EVENT_TYPES:
            zone_id = out.get("zone_id")
            zone_name = out.get("zone_name")
            has_id = isinstance(zone_id, str) and bool(zone_id.strip())
            has_name = isinstance(zone_name, str) and bool(zone_name.strip())
            if not has_id and not has_name:
                raise serializers.ValidationError(
                    {
                        "payload": (
                            "geofence events require zone_id or zone_name"
                        )
                    }
                )

        return out

    def _validate_contact_payload(self, payload: dict) -> dict:
        out = dict(payload)

        if "contact_name" in out and out["contact_name"] is not None:
            name = out["contact_name"]
            if not isinstance(name, str):
                raise serializers.ValidationError(
                    {"payload.contact_name": "Must be a string"}
                )
            cleaned = strip_control_chars(name).strip()
            if len(cleaned) > MAX_CONTACT_NAME:
                raise serializers.ValidationError(
                    {
                        "payload.contact_name": (
                            f"Cannot exceed {MAX_CONTACT_NAME} characters"
                        )
                    }
                )
            out["contact_name"] = cleaned

        if "contact_photo_url" in out and out["contact_photo_url"] is not None:
            url = out["contact_photo_url"]
            if not isinstance(url, str):
                raise serializers.ValidationError(
                    {"payload.contact_photo_url": "Must be a string"}
                )
            try:
                out["contact_photo_url"] = normalize_https_photo_url(url)
            except ValueError as exc:
                raise serializers.ValidationError(
                    {"payload.contact_photo_url": str(exc)}
                ) from exc

        for key in CONTACT_BOOL_FIELDS:
            if key not in out or out[key] is None:
                continue
            value = out[key]
            if isinstance(value, bool):
                continue
            if isinstance(value, str) and value.lower() in ("true", "false"):
                out[key] = value.lower() == "true"
                continue
            raise serializers.ValidationError(
                {f"payload.{key}": "Must be a boolean"}
            )

        return apply_contact_redaction(out)


class EventBatchSerializer(serializers.Serializer):
    device_id = serializers.UUIDField()
    events = EventItemSerializer(many=True, min_length=1, max_length=100)


class DeviceEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceEvent
        fields = [
            "id",
            "device_id",
            "event_type",
            "payload",
            "event_timestamp",
            "created_at",
        ]


class DeviceContactSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceContactSnapshot
        fields = [
            "id",
            "device_id",
            "contacts",
            "contact_count",
            "captured_at",
            "updated_at",
            "source_event_id",
        ]


class DeviceAppInventorySnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceAppInventorySnapshot
        fields = [
            "id",
            "device_id",
            "apps",
            "app_count",
            "include_system",
            "captured_at",
            "updated_at",
            "source_event_id",
        ]
