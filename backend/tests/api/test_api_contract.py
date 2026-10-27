import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


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
class TestFlutterApiContract:
    """Response shapes the Flutter app parses after login, pairing, events, and audit."""

    def test_auth_me_plans_current_and_workspace_fields(self, api_client):
        data = _register(api_client, "monitor@example.com", "Family")
        assert set(data["user"]) >= {"id", "email", "full_name"}
        assert set(data["tokens"]) >= {"access", "refresh"}
        assert set(data["tenant"]) >= {"id", "name", "slug"}
        assert set(data["subscription"]) >= {
            "plan_code",
            "plan_name",
            "is_active",
            "price_monthly_usd",
            "max_devices",
            "max_members",
            "event_retention_days",
            "features",
        }
        assert set(data["auth_methods"]) >= {"has_password", "has_google"}

        _auth(api_client, data["tokens"])
        me = api_client.get(reverse("auth-me"))
        assert me.status_code == status.HTTP_200_OK
        assert me.data["user"]["email"] == "monitor@example.com"
        assert me.data["needs_workspace"] is False
        assert me.data["subscription"]["plan_code"] == "free"

        plans = api_client.get(reverse("subscription-plans"))
        assert plans.status_code == status.HTTP_200_OK
        assert len(plans.data["plans"]) >= 3
        plan = plans.data["plans"][0]
        assert set(plan) >= {
            "code",
            "name",
            "price_monthly_usd",
            "max_devices",
            "max_members",
            "event_retention_days",
            "features",
        }

        current = api_client.get(reverse("subscription-current"))
        assert current.status_code == status.HTTP_200_OK
        assert current.data["needs_workspace"] is False
        assert current.data["subscription"]["max_devices"] == 2

    def test_pairing_devices_events_and_audit(self, api_client):
        monitored = _register(api_client, "kid@example.com", "Kid")
        monitor = _register(api_client, "parent@example.com", "Parents")

        _auth(api_client, monitored["tokens"])
        initiate = api_client.post(
            reverse("device-pair-initiate"),
            {
                "device_name": "Kid Pixel",
                "platform": "android",
                "device_fingerprint": "fp-contract-1",
            },
            format="json",
        )
        assert initiate.status_code == status.HTTP_201_CREATED
        assert set(initiate.data) >= {
            "pairing_id",
            "device_id",
            "pairing_code",
            "qr_payload",
            "expires_at",
        }

        _auth(api_client, monitor["tokens"])
        complete = api_client.post(
            reverse("device-pair-complete"),
            {
                "pairing_code": initiate.data["pairing_code"],
                "consent_scopes": [
                    "location",
                    "call_log",
                    "sms",
                    "messaging",
                    "sim",
                ],
                "consent_version": "1.0.0",
            },
            format="json",
        )
        assert complete.status_code == status.HTTP_201_CREATED
        device = complete.data["device"]
        assert set(device) >= {
            "id",
            "name",
            "platform",
            "status",
            "last_seen_at",
            "tenant_name",
            "photo_url",
        }
        assert device["status"] == "active"
        assert set(complete.data["consent"]) >= {"id", "scopes", "consent_version", "granted_at"}
        assert "location" in complete.data["consent"]["scopes"]

        devices = api_client.get(reverse("device-list"), {"page_size": 100})
        assert devices.status_code == status.HTTP_200_OK
        assert devices.data["count"] == 1
        assert devices.data["results"][0]["name"] == "Kid Pixel"

        detail = api_client.get(reverse("device-detail", kwargs={"device_id": device["id"]}))
        assert detail.status_code == status.HTTP_200_OK
        assert detail.data["owner_email"] == "kid@example.com"
        assert "location" in detail.data["consent"]["scopes"]

        bad_photo = api_client.patch(
            reverse("device-detail", kwargs={"device_id": device["id"]}),
            {"photo_url": "http://insecure.example/a.jpg"},
            format="json",
        )
        assert bad_photo.status_code == status.HTTP_400_BAD_REQUEST

        photo = api_client.patch(
            reverse("device-detail", kwargs={"device_id": device["id"]}),
            {"photo_url": "https://cdn.example.com/kid.jpg"},
            format="json",
        )
        assert photo.status_code == status.HTTP_200_OK
        assert photo.data["photo_url"] == "https://cdn.example.com/kid.jpg"

        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device["id"],
                "events": [
                    {
                        "event_type": "location.update",
                        "payload": {"lat": 23.81, "lng": 90.41, "accuracy_m": 12},
                        "idempotency_key": "loc-contract-1",
                    },
                    {
                        "event_type": "call.log",
                        "payload": {"number": "+1555", "name": "Dad", "type": "incoming", "duration_seconds": 12},
                        "idempotency_key": "call-contract-1",
                    },
                    {
                        "event_type": "sms.received",
                        "payload": {"from": "+1555", "body": "On my way"},
                        "idempotency_key": "sms-contract-1",
                    },
                    {
                        "event_type": "message.notification",
                        "payload": {"app": "com.whatsapp", "title": "Dad", "text": "Hi"},
                        "idempotency_key": "msg-contract-1",
                    },
                    {
                        "event_type": "sim.current",
                        "payload": {"sims": [{"slot": 0, "phone_number": "+8801", "carrier": "Test"}]},
                        "idempotency_key": "sim-contract-1",
                    },
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED
        assert ingest.data["accepted"] == 5

        _auth(api_client, monitor["tokens"])
        for prefix, expected_type in [
            ("location", "location.update"),
            ("call", "call.log"),
            ("sms", "sms.received"),
            ("message", "message.notification"),
            ("sim", "sim.current"),
        ]:
            events = api_client.get(
                reverse("event-list"),
                {"device_id": device["id"], "event_prefix": prefix, "page_size": 100},
            )
            assert events.status_code == status.HTTP_200_OK
            assert events.data["count"] >= 1
            item = events.data["results"][0]
            assert set(item) >= {"id", "device_id", "event_type", "payload", "event_timestamp"}
            assert item["event_type"] == expected_type

        audit = api_client.get(reverse("audit-list"), {"page_size": 100})
        assert audit.status_code == status.HTTP_200_OK
        assert audit.data["count"] >= 1
        log = audit.data["results"][0]
        assert set(log) >= {"id", "action", "resource_type", "resource_id", "created_at"}
        actions = {row["action"] for row in audit.data["results"]}
        assert "device.pairing.completed" in actions
