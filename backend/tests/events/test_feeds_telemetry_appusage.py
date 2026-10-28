"""App-usage read endpoints and the telemetry feed (new `telemetry` scope)."""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.devices.infrastructure.models.device import ConsentRecord, Device
from apps.events.infrastructure.models.snapshots import (
    DeviceAppUsageSnapshot,
    DeviceTelemetrySnapshot,
)
from apps.tenants.infrastructure.models.membership import TenantMembership


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


def _add_member(owner_data, email, role):
    from apps.accounts.infrastructure.models.user import User
    from apps.tenants.infrastructure.models.tenant import Tenant

    client = APIClient()
    data = _register(client, email, f"Tmp-{email}")
    user = User.objects.get(email=email)
    TenantMembership.objects.filter(user=user).delete()
    Tenant.objects.filter(id=data["tenant"]["id"]).delete()
    TenantMembership.objects.create(
        tenant_id=owner_data["tenant"]["id"], user=user, role=role
    )
    login = client.post(
        reverse("auth-login"),
        {"email": email, "password": "SecurePass123!"},
        format="json",
    )
    assert login.status_code == status.HTTP_200_OK
    return {"tokens": {"access": login.data["access"]}}


def _seed_device(owner_data, scopes, fingerprint="fp-feed-1"):
    device = Device.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        owner_id=owner_data["user"]["id"],
        name="Monitored",
        platform="android",
        device_fingerprint=fingerprint,
        status=Device.Status.ACTIVE,
    )
    ConsentRecord.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        device=device,
        granted_by_id=owner_data["user"]["id"],
        scopes=scopes,
        consent_version="1.0.0",
    )
    return device


def _ingest(api_client, device_id, events):
    return api_client.post(
        reverse("event-ingest"),
        {"device_id": str(device_id), "events": events},
        format="json",
    )


@pytest.mark.django_db
class TestTelemetryFeed:
    def test_ingest_latest_and_history(self, api_client):
        owner = _register(api_client, "tl-o@example.com", "TL O")
        device = _seed_device(owner, ["telemetry"], "fp-tl-1")
        _auth(api_client, owner["tokens"])

        res = _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "device.telemetry",
                    "payload": {
                        "battery_pct": 42,
                        "charging": False,
                        "network_type": "wifi",
                        "storage_free": 1000,
                        "storage_total": 4000,
                    },
                    "idempotency_key": "tl-1",
                    "timestamp": timezone.now().isoformat(),
                }
            ],
        )
        assert res.status_code == status.HTTP_202_ACCEPTED, res.data
        assert res.data["accepted"] == 1

        snap = DeviceTelemetrySnapshot.objects.get(device=device)
        assert snap.battery_pct == 42
        assert snap.network_type == "wifi"

        latest = api_client.get(
            reverse("event-telemetry-latest"), {"device_id": str(device.id)}
        )
        assert latest.status_code == status.HTTP_200_OK
        assert latest.data["battery_pct"] == 42

        hist = api_client.get(
            reverse("event-telemetry-history"), {"device_id": str(device.id)}
        )
        assert hist.status_code == status.HTTP_200_OK
        assert len(hist.data["results"]) == 1

    def test_consent_gate_rejects_without_scope(self, api_client):
        owner = _register(api_client, "tl-g@example.com", "TL G")
        device = _seed_device(owner, ["battery"], "fp-tl-2")
        _auth(api_client, owner["tokens"])
        res = _ingest(
            api_client,
            device.id,
            [{"event_type": "device.telemetry", "payload": {"battery_pct": 10}}],
        )
        assert res.status_code == status.HTTP_202_ACCEPTED
        assert res.data["accepted"] == 0
        assert res.data["rejected"] == 1

    def test_viewer_forbidden(self, api_client):
        owner = _register(api_client, "tl-ow@example.com", "TL OW")
        device = _seed_device(owner, ["telemetry"], "fp-tl-3")
        _auth(api_client, owner["tokens"])
        _ingest(
            api_client,
            device.id,
            [{"event_type": "device.telemetry", "payload": {"battery_pct": 20}}],
        )
        viewer = _add_member(owner, "tl-v@example.com", TenantMembership.Role.VIEWER)
        _auth(api_client, viewer["tokens"])
        res = api_client.get(
            reverse("event-telemetry-latest"), {"device_id": str(device.id)}
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_device_id(self, api_client):
        owner = _register(api_client, "tl-m@example.com", "TL M")
        _auth(api_client, owner["tokens"])
        res = api_client.get(reverse("event-telemetry-latest"))
        assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestAppUsageFeed:
    def test_latest_and_range_aggregation(self, api_client):
        owner = _register(api_client, "au-o@example.com", "AU O")
        device = _seed_device(owner, ["app_usage"], "fp-au-1")
        _auth(api_client, owner["tokens"])

        base = timezone.now()
        for i in range(2):
            res = _ingest(
                api_client,
                device.id,
                [
                    {
                        "event_type": "app_usage.snapshot",
                        "payload": {
                            "period_start": (
                                base - timezone.timedelta(hours=i + 1)
                            ).isoformat(),
                            "period_end": (
                                base - timezone.timedelta(hours=i)
                            ).isoformat(),
                            "apps": [
                                {
                                    "package": "com.example.app",
                                    "app_name": "Example",
                                    "foreground_ms": 1000,
                                    "launches": 2,
                                }
                            ],
                        },
                        "idempotency_key": f"au-{i}",
                        "timestamp": (
                            base - timezone.timedelta(hours=i)
                        ).isoformat(),
                    }
                ],
            )
            assert res.status_code == status.HTTP_202_ACCEPTED, res.data
            assert res.data["accepted"] == 1

        assert DeviceAppUsageSnapshot.objects.filter(device=device).exists()

        latest = api_client.get(
            reverse("event-app-usage-latest"), {"device_id": str(device.id)}
        )
        assert latest.status_code == status.HTTP_200_OK
        assert latest.data["app_count"] == 1

        rng = api_client.get(
            reverse("event-app-usage-range"), {"device_id": str(device.id)}
        )
        assert rng.status_code == status.HTTP_200_OK
        assert rng.data["app_count"] == 1
        row = rng.data["results"][0]
        assert row["package"] == "com.example.app"
        assert row["foreground_ms"] == 2000
        assert row["launches"] == 4

    def test_viewer_forbidden(self, api_client):
        owner = _register(api_client, "au-ow@example.com", "AU OW")
        device = _seed_device(owner, ["app_usage"], "fp-au-2")
        _auth(api_client, owner["tokens"])
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "app_usage.snapshot",
                    "payload": {"apps": []},
                }
            ],
        )
        viewer = _add_member(owner, "au-v@example.com", TenantMembership.Role.VIEWER)
        _auth(api_client, viewer["tokens"])
        res = api_client.get(
            reverse("event-app-usage-latest"), {"device_id": str(device.id)}
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN
