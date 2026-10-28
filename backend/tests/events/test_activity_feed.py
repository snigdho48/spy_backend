"""Merged activity feed endpoint: GET /events/activity/."""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.alerts.infrastructure.models.alert import Alert
from apps.devices.infrastructure.models.device import ConsentRecord, Device
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


def _seed_device(owner_data, scopes, fingerprint="fp-act-1"):
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
class TestActivityFeed:
    def _seed(self, api_client):
        owner = _register(api_client, "act-o@example.com", "ACT O")
        device = _seed_device(
            owner, ["location", "telemetry"], "fp-act-main"
        )
        _auth(api_client, owner["tokens"])
        base = timezone.now()
        _ingest(
            api_client,
            device.id,
            [
                {
                    "event_type": "location.update",
                    "payload": {"lat": 1.0, "lng": 2.0},
                    "idempotency_key": "act-loc-1",
                    "timestamp": (base - timezone.timedelta(minutes=30)).isoformat(),
                },
                {
                    "event_type": "device.telemetry",
                    "payload": {"battery_pct": 55, "charging": True},
                    "idempotency_key": "act-tel-1",
                    "timestamp": (base - timezone.timedelta(minutes=20)).isoformat(),
                },
            ],
        )
        # Alert row (created_at = now, so it is the newest item).
        Alert.objects.create(
            tenant_id=owner["tenant"]["id"],
            device=device,
            type=Alert.Type.LOW_BATTERY,
            severity=Alert.Severity.CRITICAL,
            title="Battery critically low",
            body="5% remaining",
            metadata={"battery_pct": 5},
        )
        return owner, device

    def test_merged_reverse_chronological(self, api_client):
        owner, device = self._seed(api_client)
        res = api_client.get(
            reverse("event-activity"), {"device_id": str(device.id)}
        )
        assert res.status_code == status.HTTP_200_OK, res.data
        results = res.data["results"]
        assert len(results) == 3
        # Newest first: alert, then telemetry, then location.
        assert results[0]["source"] == "alert"
        assert results[0]["category"] == "alerts"
        assert results[0]["severity"] == "critical"
        assert results[1]["event_type"] == "device.telemetry"
        assert results[1]["category"] == "telemetry"
        assert results[2]["event_type"] == "location.update"
        assert results[2]["category"] == "location"
        # Payload is decrypted on the way out.
        assert results[1]["payload"]["battery_pct"] == 55

    def test_category_filter(self, api_client):
        owner, device = self._seed(api_client)
        res = api_client.get(
            reverse("event-activity"),
            {"device_id": str(device.id), "types": "alerts"},
        )
        assert res.status_code == status.HTTP_200_OK
        results = res.data["results"]
        assert len(results) == 1
        assert results[0]["source"] == "alert"

    def test_cursor_pagination(self, api_client):
        owner, device = self._seed(api_client)
        first = api_client.get(
            reverse("event-activity"),
            {"device_id": str(device.id), "limit": 2},
        )
        assert first.status_code == status.HTTP_200_OK
        assert len(first.data["results"]) == 2
        assert first.data["next"]

        second = api_client.get(
            reverse("event-activity"),
            {
                "device_id": str(device.id),
                "limit": 2,
                "cursor": first.data["next"],
            },
        )
        assert second.status_code == status.HTTP_200_OK
        assert len(second.data["results"]) == 1
        assert second.data["next"] is None
        # No overlap across pages.
        first_ids = {r["id"] for r in first.data["results"]}
        second_ids = {r["id"] for r in second.data["results"]}
        assert first_ids.isdisjoint(second_ids)

    def test_viewer_forbidden(self, api_client):
        owner, device = self._seed(api_client)
        viewer = _add_member(
            owner, "act-v@example.com", TenantMembership.Role.VIEWER
        )
        _auth(api_client, viewer["tokens"])
        res = api_client.get(
            reverse("event-activity"), {"device_id": str(device.id)}
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_monitor_allowed(self, api_client):
        owner, device = self._seed(api_client)
        monitor = _add_member(
            owner, "act-m@example.com", TenantMembership.Role.MONITOR
        )
        _auth(api_client, monitor["tokens"])
        res = api_client.get(
            reverse("event-activity"), {"device_id": str(device.id)}
        )
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data["results"]) == 3

    def test_missing_device_id(self, api_client):
        owner = _register(api_client, "act-md@example.com", "ACT MD")
        _auth(api_client, owner["tokens"])
        res = api_client.get(reverse("event-activity"))
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_bad_type_rejected(self, api_client):
        owner, device = self._seed(api_client)
        res = api_client.get(
            reverse("event-activity"),
            {"device_id": str(device.id), "types": "bogus"},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
