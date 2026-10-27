import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.infrastructure.models.audit_log import AuditLog
from apps.devices.infrastructure.models.device import SafeZone
from apps.events.infrastructure.models.event import DeviceEvent


@pytest.fixture
def api_client():
    return APIClient()


def _register(api_client, email, tenant_name):
    response = api_client.post(
        reverse("auth-register"),
        {
            "email": email,
            "password": "SecurePass123!",
            "full_name": email.split("@")[0],
            "tenant_name": tenant_name,
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


def _auth(api_client, tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")


def _pair_device(api_client, monitored_tokens, monitor_tokens, fingerprint="fp-zone-1"):
    _auth(api_client, monitored_tokens)
    initiate = api_client.post(
        reverse("device-pair-initiate"),
        {
            "device_name": "Zone Phone",
            "platform": "android",
            "device_fingerprint": fingerprint,
        },
        format="json",
    )
    assert initiate.status_code == status.HTTP_201_CREATED
    device_id = initiate.data["device_id"]
    code = initiate.data["pairing_code"]

    _auth(api_client, monitor_tokens)
    complete = api_client.post(
        reverse("device-pair-complete"),
        {
            "pairing_code": code.replace("-", ""),
            "consent_scopes": ["location", "battery"],
            "consent_version": "1.0.0",
        },
        format="json",
    )
    assert complete.status_code == status.HTTP_201_CREATED
    return device_id


@pytest.mark.django_db
class TestSafeZones:
    def test_monitor_crud_and_audit(self, api_client):
        monitored = _register(api_client, "zone-kid@example.com", "Kid Zone")
        monitor = _register(api_client, "zone-parent@example.com", "Parent Zone")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-zone-crud"
        )

        _auth(api_client, monitor["tokens"])
        created = api_client.post(
            reverse("safe-zone-list"),
            {
                "name": "School",
                "address": "12 Education Rd",
                "lat": 23.81,
                "lng": 90.41,
                "radius_m": 150,
                "device_id": device_id,
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED
        zone_id = created.data["id"]
        assert created.data["display_label"] == "Safe Zone: School"
        assert str(created.data["device_id"]) == str(device_id)

        listed = api_client.get(reverse("safe-zone-list"))
        assert listed.status_code == status.HTTP_200_OK
        assert len(listed.data["results"]) == 1

        patched = api_client.patch(
            reverse("safe-zone-detail", kwargs={"zone_id": zone_id}),
            {"radius_m": 200, "name": "High School"},
            format="json",
        )
        assert patched.status_code == status.HTTP_200_OK
        assert patched.data["radius_m"] == 200
        assert patched.data["name"] == "High School"

        deleted = api_client.delete(
            reverse("safe-zone-detail", kwargs={"zone_id": zone_id})
        )
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert SafeZone.objects.count() == 0

        actions = set(
            AuditLog.objects.filter(resource_type="safe_zone").values_list(
                "action", flat=True
            )
        )
        assert "safe_zone.created" in actions
        assert "safe_zone.updated" in actions
        assert "safe_zone.deleted" in actions

    def test_monitored_user_can_list_applicable_zones_readonly(self, api_client):
        monitored = _register(api_client, "zone-kid2@example.com", "Kid Zone 2")
        monitor = _register(api_client, "zone-parent2@example.com", "Parent Zone 2")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-zone-ro"
        )

        _auth(api_client, monitor["tokens"])
        api_client.post(
            reverse("safe-zone-list"),
            {
                "name": "Home",
                "lat": 23.7,
                "lng": 90.3,
                "radius_m": 100,
                "device_id": device_id,
            },
            format="json",
        )
        api_client.post(
            reverse("safe-zone-list"),
            {
                "name": "Workspace Wide",
                "lat": 23.75,
                "lng": 90.35,
                "radius_m": 80,
            },
            format="json",
        )

        _auth(api_client, monitor["tokens"])
        home_id = next(
            z["id"]
            for z in api_client.get(reverse("safe-zone-list")).data["results"]
            if z["name"] == "Home"
        )

        _auth(api_client, monitored["tokens"])
        listed = api_client.get(reverse("safe-zone-list"))
        assert listed.status_code == status.HTTP_200_OK
        names = {z["name"] for z in listed.data["results"]}
        assert names == {"Home", "Workspace Wide"}

        # Cannot mutate family-workspace zones from the monitored account.
        patch_denied = api_client.patch(
            reverse("safe-zone-detail", kwargs={"zone_id": home_id}),
            {"radius_m": 999},
            format="json",
        )
        assert patch_denied.status_code in (
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        )

    def test_geofence_requires_known_zone_and_maps_to_location_consent(
        self, api_client
    ):
        monitored = _register(api_client, "zone-kid3@example.com", "Kid Zone 3")
        monitor = _register(api_client, "zone-parent3@example.com", "Parent Zone 3")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-zone-geo"
        )

        _auth(api_client, monitor["tokens"])
        zone = api_client.post(
            reverse("safe-zone-list"),
            {"name": "School", "lat": 23.81, "lng": 90.41, "radius_m": 120},
            format="json",
        )
        assert zone.status_code == status.HTTP_201_CREATED
        zone_id = zone.data["id"]

        _auth(api_client, monitored["tokens"])
        unknown = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "geofence.enter",
                        "payload": {"zone_name": "Nowhere", "lat": 23.81, "lng": 90.41},
                        "idempotency_key": "geo-unknown-1",
                        "timestamp": timezone.now().isoformat(),
                    }
                ],
            },
            format="json",
        )
        assert unknown.status_code == status.HTTP_202_ACCEPTED
        assert unknown.data["accepted"] == 0
        assert unknown.data["rejected"] == 1

        missing = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "geofence.exit",
                        "payload": {"lat": 23.81, "lng": 90.41},
                        "idempotency_key": "geo-missing-1",
                    }
                ],
            },
            format="json",
        )
        assert missing.status_code == status.HTTP_400_BAD_REQUEST

        ok = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "geofence.enter",
                        "payload": {
                            "zone_id": zone_id,
                            "lat": 23.81,
                            "lng": 90.41,
                        },
                        "idempotency_key": "geo-ok-1",
                        "timestamp": timezone.now().isoformat(),
                    },
                    {
                        "event_type": "location.update",
                        "payload": {
                            "lat": 23.81,
                            "lng": 90.41,
                            "place_name": "Near gate",
                            "address": "School gate",
                            "zone_id": zone_id,
                        },
                        "idempotency_key": "loc-place-1",
                        "timestamp": timezone.now().isoformat(),
                    },
                ],
            },
            format="json",
        )
        assert ok.status_code == status.HTTP_202_ACCEPTED
        assert ok.data["accepted"] == 2

        geo = DeviceEvent.objects.get(idempotency_key="geo-ok-1")
        assert geo.payload["zone_id"] == zone_id
        assert geo.payload["zone_name"] == "Safe Zone: School"
        assert geo.payload["place_name"] == "Safe Zone: School"

        loc = DeviceEvent.objects.get(idempotency_key="loc-place-1")
        assert loc.payload["place_name"] == "Near gate"
        assert loc.payload["zone_name"] == "Safe Zone: School"
        assert loc.payload["address"] == "School gate"

    def test_geofence_without_location_consent_rejected(self, api_client):
        monitored = _register(api_client, "zone-kid4@example.com", "Kid Zone 4")
        monitor = _register(api_client, "zone-parent4@example.com", "Parent Zone 4")

        _auth(api_client, monitored["tokens"])
        initiate = api_client.post(
            reverse("device-pair-initiate"),
            {
                "device_name": "No Loc Phone",
                "platform": "android",
                "device_fingerprint": "fp-zone-noconsent",
            },
            format="json",
        )
        device_id = initiate.data["device_id"]
        code = initiate.data["pairing_code"]

        _auth(api_client, monitor["tokens"])
        complete = api_client.post(
            reverse("device-pair-complete"),
            {
                "pairing_code": code.replace("-", ""),
                "consent_scopes": ["battery"],
                "consent_version": "1.0.0",
            },
            format="json",
        )
        assert complete.status_code == status.HTTP_201_CREATED

        zone = api_client.post(
            reverse("safe-zone-list"),
            {"name": "Park", "lat": 23.8, "lng": 90.4, "radius_m": 50},
            format="json",
        )
        assert zone.status_code == status.HTTP_201_CREATED

        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "geofence.enter",
                        "payload": {"zone_name": "Park"},
                        "idempotency_key": "geo-noconsent-1",
                    }
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED
        assert ingest.data["accepted"] == 0
        assert "location" in ingest.data["errors"][0]["message"].lower()
