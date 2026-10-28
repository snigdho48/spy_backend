"""Log redaction and field-encryption round-trips."""

import logging

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.devices.infrastructure.models.device import ConsentRecord, Device
from apps.events.infrastructure.models.event import DeviceEvent
from core.crypto.field_encryption import (
    decrypt_payload,
    encrypt_payload,
    is_encryption_enabled,
)
from core.logging_filters import SensitiveDataFilter


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


class TestLogRedaction:
    def test_filter_redacts_body_phone_and_jwt(self):
        f = SensitiveDataFilter()
        raw = (
            'sms body=hello-secret phone=+15551234567 '
            'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
            'eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature'
        )
        redacted = f.redact(raw)
        assert "hello-secret" not in redacted
        assert "+15551234567" not in redacted
        assert "eyJhbGciOi" not in redacted
        assert "signature" not in redacted
        assert "[REDACTED]" in redacted

    def test_filter_attached_to_logger(self):
        record = logging.LogRecord(
            name="apps.events",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg='payload body="secret-text" phone=+19998887777',
            args=(),
            exc_info=None,
        )
        SensitiveDataFilter().filter(record)
        assert "secret-text" not in record.msg
        assert "+19998887777" not in record.msg


@pytest.mark.django_db
class TestFieldEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        assert is_encryption_enabled()
        payload = {"body": "hi mom", "from": "+1555", "lat": 1.2}
        stored = encrypt_payload(payload)
        assert stored["body"].startswith("enc:v1:")
        assert stored["from"].startswith("enc:v1:")
        assert stored["lat"] == 1.2
        assert decrypt_payload(stored) == payload

    def test_ingest_stores_ciphertext_api_returns_plaintext(self, api_client):
        data = _register(api_client, "crypto@example.com", "CryptoOrg")
        _auth(api_client, data["tokens"])
        device = Device.objects.create(
            tenant_id=data["tenant"]["id"],
            owner_id=data["user"]["id"],
            name="CryptoPhone",
            platform="android",
            device_fingerprint="fp-crypto-1",
            status=Device.Status.ACTIVE,
        )
        ConsentRecord.objects.create(
            tenant_id=data["tenant"]["id"],
            device=device,
            granted_by_id=data["user"]["id"],
            scopes=["sms"],
            consent_version="1.0.0",
        )
        response = api_client.post(
            reverse("event-ingest"),
            {
                "device_id": str(device.id),
                "events": [
                    {
                        "event_type": "sms.received",
                        "payload": {"from": "+15550001111", "body": "ciphertext-me"},
                        "idempotency_key": "crypto-sms-1",
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.data["accepted"] == 1

        row = DeviceEvent.objects.get(idempotency_key="crypto-sms-1")
        assert row.payload["body"].startswith("enc:v1:")
        assert "ciphertext-me" not in row.payload["body"]

        listed = api_client.get(
            reverse("event-list"), {"device_id": str(device.id)}
        )
        assert listed.status_code == status.HTTP_200_OK
        bodies = [e["payload"]["body"] for e in listed.data["results"]]
        assert "ciphertext-me" in bodies
