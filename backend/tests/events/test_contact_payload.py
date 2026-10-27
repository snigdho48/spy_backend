import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

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


def _pair_device(
    api_client,
    monitored_tokens,
    monitor_tokens,
    fingerprint="fp-contact-1",
    scopes=None,
):
    _auth(api_client, monitored_tokens)
    initiate = api_client.post(
        reverse("device-pair-initiate"),
        {
            "device_name": "Contact Phone",
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
            "consent_scopes": scopes
            or ["location", "call_log", "sms", "battery"],
            "consent_version": "1.0.0",
        },
        format="json",
    )
    assert complete.status_code == status.HTTP_201_CREATED
    return device_id


@pytest.mark.django_db
class TestContactPayload:
    def test_bad_photo_url_rejected(self, api_client):
        monitored = _register(api_client, "c-kid1@example.com", "C Kid 1")
        monitor = _register(api_client, "c-par1@example.com", "C Par 1")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-c-url"
        )

        _auth(api_client, monitored["tokens"])
        for bad_url in (
            "http://example.com/photo.jpg",
            "javascript:alert(1)",
            "https://user:pass@example.com/p.jpg",
            "not-a-url",
        ):
            resp = api_client.post(
                reverse("event-ingest"),
                {
                    "device_id": device_id,
                    "events": [
                        {
                            "event_type": "sms.received",
                            "payload": {
                                "from": "+1555",
                                "body": "hi",
                                "contact_photo_url": bad_url,
                            },
                            "idempotency_key": f"bad-url-{hash(bad_url) & 0xffff}",
                        }
                    ],
                },
                format="json",
            )
            assert resp.status_code == status.HTTP_400_BAD_REQUEST, bad_url

    def test_oversize_contact_name_rejected(self, api_client):
        monitored = _register(api_client, "c-kid2@example.com", "C Kid 2")
        monitor = _register(api_client, "c-par2@example.com", "C Par 2")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-c-size"
        )

        _auth(api_client, monitored["tokens"])
        resp = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "call.log",
                        "payload": {
                            "number": "+1555",
                            "contact_name": "A" * 129,
                        },
                        "idempotency_key": "oversize-name-1",
                    }
                ],
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_flags_round_trip_via_events_list(self, api_client):
        monitored = _register(api_client, "c-kid3@example.com", "C Kid 3")
        monitor = _register(api_client, "c-par3@example.com", "C Par 3")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-c-rt"
        )

        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "sms.received",
                        "payload": {
                            "from": "+15551212",
                            "body": "On my way",
                            "contact_name": "Dad\x00 Safe",
                            "contact_photo_url": "https://cdn.example.com/dad.jpg",
                            "is_known": True,
                            "is_flagged": True,
                            "is_redacted": False,
                        },
                        "idempotency_key": "sms-flags-1",
                        "timestamp": timezone.now().isoformat(),
                    },
                    {
                        "event_type": "call.log",
                        "payload": {
                            "number": "+15551212",
                            "type": "incoming",
                            "duration_seconds": 40,
                            "contact_name": "Dad",
                            "is_known": True,
                            "is_flagged": False,
                        },
                        "idempotency_key": "call-flags-1",
                        "timestamp": timezone.now().isoformat(),
                    },
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED
        assert ingest.data["accepted"] == 2

        sms_row = DeviceEvent.objects.get(idempotency_key="sms-flags-1")
        assert sms_row.payload["contact_name"] == "Dad Safe"
        assert sms_row.payload["contact_photo_url"].startswith("https://")
        assert sms_row.payload["is_known"] is True
        assert sms_row.payload["is_flagged"] is True

        _auth(api_client, monitor["tokens"])
        listed = api_client.get(
            reverse("event-list"),
            {"device_id": device_id, "event_prefix": "sms", "page_size": 50},
        )
        assert listed.status_code == status.HTTP_200_OK
        item = next(
            r for r in listed.data["results"] if r["payload"].get("is_flagged")
        )
        assert item["payload"]["contact_name"] == "Dad Safe"
        assert item["payload"]["is_known"] is True
        assert item["payload"]["contact_photo_url"] == (
            "https://cdn.example.com/dad.jpg"
        )

    def test_redaction_strips_body(self, api_client):
        monitored = _register(api_client, "c-kid4@example.com", "C Kid 4")
        monitor = _register(api_client, "c-par4@example.com", "C Par 4")
        device_id = _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-c-red"
        )

        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "sms.received",
                        "payload": {
                            "from": "+1555",
                            "body": "secret message",
                            "text": "also secret",
                            "preview": "preview secret",
                            "contact_name": "Mom",
                            "is_redacted": True,
                        },
                        "idempotency_key": "sms-redact-1",
                    }
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED
        assert ingest.data["accepted"] == 1

        row = DeviceEvent.objects.get(idempotency_key="sms-redact-1")
        assert row.payload["is_redacted"] is True
        assert row.payload["body"] == ""
        assert row.payload["text"] == ""
        assert row.payload["preview"] == ""
        assert row.payload["contact_name"] == "Mom"

    def test_sms_and_call_consent_still_enforced(self, api_client):
        monitored = _register(api_client, "c-kid5@example.com", "C Kid 5")
        monitor = _register(api_client, "c-par5@example.com", "C Par 5")
        device_id = _pair_device(
            api_client,
            monitored["tokens"],
            monitor["tokens"],
            fingerprint="fp-c-consent",
            scopes=["battery"],
        )

        _auth(api_client, monitored["tokens"])
        ingest = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": device_id,
                "events": [
                    {
                        "event_type": "sms.received",
                        "payload": {
                            "from": "+1",
                            "body": "x",
                            "contact_name": "X",
                            "is_known": True,
                        },
                        "idempotency_key": "sms-noconsent-1",
                    },
                    {
                        "event_type": "call.log",
                        "payload": {
                            "number": "+1",
                            "contact_name": "X",
                            "is_flagged": True,
                        },
                        "idempotency_key": "call-noconsent-1",
                    },
                ],
            },
            format="json",
        )
        assert ingest.status_code == status.HTTP_202_ACCEPTED
        assert ingest.data["accepted"] == 0
        assert ingest.data["rejected"] == 2
        messages = " ".join(e["message"].lower() for e in ingest.data["errors"])
        assert "sms" in messages or "consent" in messages
        assert "call" in messages or "consent" in messages
