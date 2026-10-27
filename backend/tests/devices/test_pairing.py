import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.devices.infrastructure.models.device import Device


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
class TestCrossAccountPairing:
    def test_monitored_device_can_initiate_pairing(self, api_client):
        monitored_data = _register(api_client, "monitored@example.com", "Monitored Org")
        _auth(api_client, monitored_data["tokens"])

        initiate = api_client.post(
            reverse("device-pair-initiate"),
            {
                "device_name": "Kid Phone",
                "platform": "android",
                "device_fingerprint": "fp-monitored-1",
            },
            format="json",
        )
        assert initiate.status_code == status.HTTP_201_CREATED
        assert initiate.data["pairing_code"]

    def test_approver_completes_pairing_from_different_account(self, api_client):
        monitored_data = _register(api_client, "kid@example.com", "Kid Personal")
        monitor_data = _register(api_client, "parent@example.com", "Family Monitor")

        _auth(api_client, monitored_data["tokens"])
        initiate = api_client.post(
            reverse("device-pair-initiate"),
            {
                "device_name": "Kid Phone",
                "platform": "android",
                "device_fingerprint": "fp-cross-1",
            },
            format="json",
        )
        pairing_code = initiate.data["pairing_code"]

        _auth(api_client, monitor_data["tokens"])
        complete = api_client.post(
            reverse("device-pair-complete"),
            {
                "pairing_code": pairing_code.replace("-", ""),
                "consent_scopes": ["location", "battery"],
                "consent_version": "1.0.0",
            },
            format="json",
        )
        assert complete.status_code == status.HTTP_201_CREATED

        devices = api_client.get(reverse("device-list"), format="json")
        assert devices.status_code == status.HTTP_200_OK
        assert devices.data["count"] == 1
        assert devices.data["results"][0]["name"] == "Kid Phone"

        device = Device.objects.get(name="Kid Phone")
        assert str(device.tenant_id) == str(monitor_data["tenant"]["id"])
