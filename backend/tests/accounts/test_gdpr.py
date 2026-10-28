"""GDPR account deletion, data export, and retention purge."""

import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.infrastructure.models.user import User
from apps.devices.infrastructure.models.device import Device
from apps.events.application.services.retention_service import RetentionService
from apps.events.infrastructure.models.event import DeviceEvent
from apps.events.tasks import purge_expired_events
from apps.tenants.infrastructure.models.tenant import Tenant


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


@pytest.mark.django_db
class TestAccountExport:
    def test_export_includes_owned_devices_and_events(self, api_client):
        data = _register(api_client, "export@example.com", "ExportOrg")
        _auth(api_client, data["tokens"])
        device = Device.objects.create(
            tenant_id=data["tenant"]["id"],
            owner_id=data["user"]["id"],
            name="Phone",
            platform="android",
            device_fingerprint="fp-export-1",
            status=Device.Status.ACTIVE,
        )
        DeviceEvent.objects.create(
            tenant_id=data["tenant"]["id"],
            device=device,
            event_type="sms.received",
            payload={"body": "hello", "from": "+100"},
            event_timestamp=timezone.now(),
        )

        response = api_client.get(reverse("auth-me-export"))
        assert response.status_code == status.HTTP_200_OK
        payload = json.loads(b"".join(response.streaming_content).decode())
        assert payload["user"]["email"] == "export@example.com"
        assert len(payload["devices"]) == 1
        assert payload["devices"][0]["name"] == "Phone"
        assert len(payload["devices"][0]["events"]) == 1
        assert payload["devices"][0]["events"][0]["payload"]["body"] == "hello"


@pytest.mark.django_db
class TestAccountDeletion:
    def test_delete_removes_user_and_owned_devices(self, api_client):
        data = _register(api_client, "erase@example.com", "EraseOrg")
        _auth(api_client, data["tokens"])
        device = Device.objects.create(
            tenant_id=data["tenant"]["id"],
            owner_id=data["user"]["id"],
            name="Gone",
            platform="android",
            device_fingerprint="fp-erase-1",
            status=Device.Status.ACTIVE,
        )
        DeviceEvent.objects.create(
            tenant_id=data["tenant"]["id"],
            device=device,
            event_type="battery.update",
            payload={"level": 50},
            event_timestamp=timezone.now(),
        )
        user_id = data["user"]["id"]
        device_id = device.id

        response = api_client.delete(reverse("auth-me-delete"))
        assert response.status_code == status.HTTP_200_OK
        assert not User.objects.filter(pk=user_id).exists()
        assert not Device.objects.filter(pk=device_id).exists()
        assert not DeviceEvent.objects.filter(device_id=device_id).exists()


@pytest.mark.django_db
class TestRetentionPurge:
    def test_purges_events_older_than_plan_window(self, api_client):
        data = _register(api_client, "retain@example.com", "RetainOrg")
        tenant = Tenant.objects.get(pk=data["tenant"]["id"])
        assert tenant.plan == Tenant.Plan.FREE  # 7-day retention
        device = Device.objects.create(
            tenant=tenant,
            owner_id=data["user"]["id"],
            name="OldPhone",
            platform="android",
            device_fingerprint="fp-retain-1",
            status=Device.Status.ACTIVE,
        )
        old = DeviceEvent.objects.create(
            tenant=tenant,
            device=device,
            event_type="sms.received",
            payload={"body": "old"},
            event_timestamp=timezone.now() - timedelta(days=10),
        )
        recent = DeviceEvent.objects.create(
            tenant=tenant,
            device=device,
            event_type="sms.received",
            payload={"body": "new"},
            event_timestamp=timezone.now() - timedelta(days=1),
        )

        result = RetentionService().purge_all(chunk_size=50)
        assert result["events_deleted"] >= 1
        assert not DeviceEvent.objects.filter(pk=old.pk).exists()
        assert DeviceEvent.objects.filter(pk=recent.pk).exists()

        # Celery task wrapper is idempotent
        again = purge_expired_events(chunk_size=50)
        assert again["events_deleted"] == 0
