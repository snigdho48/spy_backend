"""CSV / PDF device export endpoints."""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.alerts.infrastructure.models.alert import Alert
from apps.devices.infrastructure.models.device import ConsentRecord, Device
from apps.events.infrastructure.models.event import DeviceEvent
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


def _seed(owner_data, fingerprint="fp-ex-1"):
    device = Device.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        owner_id=owner_data["user"]["id"],
        name="Export Phone",
        platform="android",
        device_fingerprint=fingerprint,
        status=Device.Status.ACTIVE,
    )
    ConsentRecord.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        device=device,
        granted_by_id=owner_data["user"]["id"],
        scopes=["location", "app_usage", "telemetry", "sos"],
        consent_version="1.0.0",
    )
    now = timezone.now()
    DeviceEvent.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        device=device,
        event_type="location.update",
        payload={"lat": 23.8, "lng": 90.4},
        event_timestamp=now,
        idempotency_key="ex-loc-1",
    )
    DeviceEvent.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        device=device,
        event_type="app_usage.snapshot",
        payload={"apps": [{"package": "com.x", "foreground_ms": 10}]},
        event_timestamp=now,
        idempotency_key="ex-au-1",
    )
    Alert.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        device=device,
        type=Alert.Type.SOS,
        severity=Alert.Severity.CRITICAL,
        title="SOS",
        body="test",
    )
    return device


@pytest.mark.django_db
class TestDeviceExport:
    def test_csv_happy_path(self, api_client):
        owner = _register(api_client, "ex-o@example.com", "EX O")
        device = _seed(owner)
        _auth(api_client, owner["tokens"])
        res = api_client.get(
            reverse("event-export"),
            {
                "device_id": str(device.id),
                "export_format": "csv",
                "feeds": "events,locations,app_usage,alerts",
            },
        )
        assert res.status_code == status.HTTP_200_OK, getattr(res, "data", res.content)
        assert "text/csv" in res["Content-Type"]
        body = b"".join(res.streaming_content).decode("utf-8")
        assert "feed,timestamp" in body
        assert "locations" in body
        assert "app_usage" in body
        assert "alerts" in body
        assert "SOS" in body

    def test_pdf_happy_path(self, api_client):
        owner = _register(api_client, "ex-p@example.com", "EX P")
        device = _seed(owner, fingerprint="fp-ex-2")
        _auth(api_client, owner["tokens"])
        res = api_client.get(
            reverse("event-export"),
            {
                "device_id": str(device.id),
                "export_format": "pdf",
                "feeds": "events,alerts",
            },
        )
        assert res.status_code == status.HTTP_200_OK
        assert res["Content-Type"] == "application/pdf"
        assert res.content[:4] == b"%PDF"

    def test_viewer_forbidden(self, api_client):
        owner = _register(api_client, "ex-ow@example.com", "EX OW")
        device = _seed(owner, fingerprint="fp-ex-3")
        viewer = _add_member(
            owner, "ex-v@example.com", TenantMembership.Role.VIEWER
        )
        _auth(api_client, viewer["tokens"])
        res = api_client.get(
            reverse("event-export"),
            {"device_id": str(device.id), "export_format": "csv"},
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_device_id(self, api_client):
        owner = _register(api_client, "ex-m@example.com", "EX M")
        _auth(api_client, owner["tokens"])
        res = api_client.get(reverse("event-export"), {"export_format": "csv"})
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_bad_format(self, api_client):
        owner = _register(api_client, "ex-b@example.com", "EX B")
        device = _seed(owner, fingerprint="fp-ex-4")
        _auth(api_client, owner["tokens"])
        res = api_client.get(
            reverse("event-export"),
            {"device_id": str(device.id), "export_format": "xlsx"},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_bad_feed(self, api_client):
        owner = _register(api_client, "ex-f@example.com", "EX F")
        device = _seed(owner, fingerprint="fp-ex-5")
        _auth(api_client, owner["tokens"])
        res = api_client.get(
            reverse("event-export"),
            {"device_id": str(device.id), "feeds": "nope"},
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
