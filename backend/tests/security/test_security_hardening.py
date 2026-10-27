import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.devices.application.services.pairing_service import ConsentService
from apps.devices.infrastructure.models.device import ConsentRecord, Device
from apps.tenants.infrastructure.models.membership import TenantMembership
from core.domain.exceptions import ConsentRequiredError


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


def _set_role(email, role):
    membership = TenantMembership.objects.get(user__email=email)
    membership.role = role
    membership.save(update_fields=["role"])


@pytest.mark.django_db
class TestSubscribeRoleGate:
    @pytest.mark.parametrize("role", ["viewer", "monitor"])
    def test_non_admin_cannot_change_plan(self, api_client, role):
        data = _register(api_client, "member@example.com", "Org")
        _set_role("member@example.com", role)
        _auth(api_client, data["tokens"])

        response = api_client.post(
            reverse("subscription-subscribe"), {"plan_code": "pro"}, format="json"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["error"]["code"] == "forbidden"

    @pytest.mark.parametrize("role", ["owner", "admin"])
    def test_owner_and_admin_can_change_plan(self, api_client, role):
        data = _register(api_client, "boss@example.com", "Org")
        _set_role("boss@example.com", role)
        _auth(api_client, data["tokens"])

        response = api_client.post(
            reverse("subscription-subscribe"), {"plan_code": "pro"}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["subscription"]["plan_code"] == "pro"


@pytest.mark.django_db
class TestAuditRoleGate:
    def test_viewer_cannot_read_audit(self, api_client):
        role = "viewer"
        data = _register(api_client, "member@example.com", "Org")
        _set_role("member@example.com", role)
        _auth(api_client, data["tokens"])

        response = api_client.get(reverse("audit-list"))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["error"]["code"] == "forbidden"

    @pytest.mark.parametrize("role", ["owner", "admin", "monitor"])
    def test_owner_admin_and_monitor_can_read_audit(self, api_client, role):
        data = _register(api_client, "boss@example.com", "Org")
        _set_role("boss@example.com", role)
        _auth(api_client, data["tokens"])

        response = api_client.get(reverse("audit-list"))
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestConsentScopeRejection:
    def _device_with_scopes(self, api_client, scopes):
        data = _register(api_client, "kid@example.com", "Kid")
        user_id = data["user"]["id"]
        device = Device.objects.create(
            tenant_id=data["tenant"]["id"],
            owner_id=user_id,
            name="Kid Phone",
            platform="android",
            device_fingerprint="fp-sec-1",
            status=Device.Status.ACTIVE,
        )
        ConsentRecord.objects.create(
            tenant_id=data["tenant"]["id"],
            device=device,
            granted_by_id=user_id,
            scopes=scopes,
            consent_version="1.0.0",
        )
        return data, device

    def test_service_rejects_event_without_granted_scope(self, api_client):
        _, device = self._device_with_scopes(api_client, ["location"])
        ConsentService().validate_event_scope(device, "location.update")
        with pytest.raises(ConsentRequiredError):
            ConsentService().validate_event_scope(device, "sms.received")

    def test_ingest_rejects_ungranted_scope_event(self, api_client):
        data, device = self._device_with_scopes(api_client, ["location"])
        _auth(api_client, data["tokens"])

        response = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": str(device.id),
                "events": [
                    {
                        "event_type": "location.update",
                        "payload": {"lat": 1, "lng": 2},
                        "idempotency_key": "sec-loc-1",
                    },
                    {
                        "event_type": "sms.received",
                        "payload": {"from": "+1555", "body": "hi"},
                        "idempotency_key": "sec-sms-1",
                    },
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data["accepted"] == 1
        assert response.data["rejected"] == 1
        assert "sms" in response.data["errors"][0]["message"]

class TestWebSocketConsumerHelpers:
    """DB-free checks of token preference and delivery filtering."""

    def _consumer(self, scope):
        import json  # noqa: F401
        from apps.events.presentation.consumers.event_consumer import EventStreamConsumer

        consumer = EventStreamConsumer.__new__(EventStreamConsumer)
        consumer.scope = scope
        consumer.device_filter = None
        consumer.sent = []

        async def _send(text_data=None, **kwargs):
            consumer.sent.append(text_data)

        consumer.send = _send
        return consumer

    def test_header_token_preferred_over_query(self):
        consumer = self._consumer(
            {
                "query_string": b"token=querytoken",
                "headers": [(b"authorization", b"Bearer headertoken")],
            }
        )
        assert consumer._extract_token() == "headertoken"

    def test_query_token_still_supported(self):
        consumer = self._consumer({"query_string": b"token=querytoken", "headers": []})
        assert consumer._extract_token() == "querytoken"

    def test_batch_filtered_by_device_filter(self):
        import asyncio
        import json

        consumer = self._consumer({"query_string": b"", "headers": []})
        batch = {
            "data": [
                {"device_id": "aaaaaaaa-0000-0000-0000-000000000001", "event_type": "a"},
                {"device_id": "aaaaaaaa-0000-0000-0000-000000000002", "event_type": "b"},
            ]
        }
        asyncio.run(consumer.events_batch(batch))
        assert len(consumer.sent) == 2  # no filter = legacy behaviour

        consumer.sent.clear()
        consumer.device_filter = {"aaaaaaaa-0000-0000-0000-000000000002"}
        asyncio.run(consumer.events_batch(batch))
        assert [json.loads(s)["event_type"] for s in consumer.sent] == ["b"]