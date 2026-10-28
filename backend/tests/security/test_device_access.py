"""Object-level authorization (BOLA) for per-device reads."""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.devices.infrastructure.models.device import ConsentRecord, Device
from apps.events.infrastructure.models.event import DeviceEvent
from apps.events.infrastructure.models.snapshots import (
    DeviceAppInventorySnapshot,
    DeviceContactSnapshot,
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
    """Register a second user and attach them to the owner's tenant."""
    from apps.accounts.infrastructure.models.user import User
    from apps.tenants.infrastructure.models.tenant import Tenant

    # Create user without a competing workspace by registering then re-homing.
    client = APIClient()
    data = _register(client, email, f"Tmp-{email}")
    user = User.objects.get(email=email)
    # Drop auto-created tenant membership and join owner's tenant.
    TenantMembership.objects.filter(user=user).delete()
    Tenant.objects.filter(id=data["tenant"]["id"]).delete()
    TenantMembership.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        user=user,
        role=role,
    )
    # Re-login to get tokens scoped to the new membership
    login = client.post(
        reverse("auth-login"),
        {"email": email, "password": "SecurePass123!"},
        format="json",
    )
    assert login.status_code == status.HTTP_200_OK
    return {
        "user": {"id": str(user.id), "email": email},
        "tokens": {
            "access": login.data["access"],
            "refresh": login.data["refresh"],
        },
        "tenant": owner_data["tenant"],
    }


def _seed_device_with_data(owner_data):
    device = Device.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        owner_id=owner_data["user"]["id"],
        name="Monitored",
        platform="android",
        device_fingerprint="fp-bola-1",
        status=Device.Status.ACTIVE,
    )
    ConsentRecord.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        device=device,
        granted_by_id=owner_data["user"]["id"],
        scopes=["sms", "contacts", "app_usage"],
        consent_version="1.0.0",
    )
    now = timezone.now()
    DeviceEvent.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        device=device,
        event_type="sms.received",
        payload={"from": "+15551212", "body": "secret"},
        event_timestamp=now,
    )
    DeviceContactSnapshot.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        device=device,
        contacts=[{"name": "Ada", "phones": ["+1555"]}],
        contact_count=1,
        captured_at=now,
    )
    DeviceAppInventorySnapshot.objects.create(
        tenant_id=owner_data["tenant"]["id"],
        device=device,
        apps=[{"package": "com.example", "name": "Ex"}],
        app_count=1,
        captured_at=now,
    )
    return device


@pytest.mark.django_db
class TestDeviceObjectAuthorization:
    def test_viewer_denied_events_contacts_apps(self, api_client):
        owner = _register(api_client, "owner-bola@example.com", "BolaOrg")
        device = _seed_device_with_data(owner)
        viewer = _add_member(owner, "viewer-bola@example.com", TenantMembership.Role.VIEWER)

        _auth(api_client, viewer["tokens"])

        events = api_client.get(
            reverse("event-list"), {"device_id": str(device.id)}
        )
        assert events.status_code == status.HTTP_403_FORBIDDEN
        assert events.data["error"]["code"] == "forbidden"

        contacts = api_client.get(
            reverse("event-contacts-latest"), {"device_id": str(device.id)}
        )
        assert contacts.status_code == status.HTTP_403_FORBIDDEN

        apps = api_client.get(
            reverse("event-app-inventory-latest"), {"device_id": str(device.id)}
        )
        assert apps.status_code == status.HTTP_403_FORBIDDEN

        detail = api_client.get(
            reverse("device-detail", kwargs={"device_id": device.id})
        )
        assert detail.status_code == status.HTTP_403_FORBIDDEN

    def test_monitor_can_read_device_data(self, api_client):
        owner = _register(api_client, "owner2-bola@example.com", "BolaOrg2")
        device = _seed_device_with_data(owner)
        monitor = _add_member(
            owner, "monitor-bola@example.com", TenantMembership.Role.MONITOR
        )

        _auth(api_client, monitor["tokens"])

        events = api_client.get(
            reverse("event-list"), {"device_id": str(device.id)}
        )
        assert events.status_code == status.HTTP_200_OK
        assert events.data["count"] >= 1

        contacts = api_client.get(
            reverse("event-contacts-latest"), {"device_id": str(device.id)}
        )
        assert contacts.status_code == status.HTTP_200_OK
        assert contacts.data["contact_count"] == 1

        apps = api_client.get(
            reverse("event-app-inventory-latest"), {"device_id": str(device.id)}
        )
        assert apps.status_code == status.HTTP_200_OK
        assert apps.data["app_count"] == 1

        detail = api_client.get(
            reverse("device-detail", kwargs={"device_id": device.id})
        )
        assert detail.status_code == status.HTTP_200_OK

    def test_viewer_event_list_excludes_others_devices(self, api_client):
        owner = _register(api_client, "owner3-bola@example.com", "BolaOrg3")
        device = _seed_device_with_data(owner)
        viewer = _add_member(
            owner, "viewer3-bola@example.com", TenantMembership.Role.VIEWER
        )
        _auth(api_client, viewer["tokens"])
        # No device_id → empty (viewer owns nothing in this tenant)
        events = api_client.get(reverse("event-list"))
        assert events.status_code == status.HTTP_200_OK
        assert events.data["count"] == 0
        assert str(device.id) not in str(events.data)
