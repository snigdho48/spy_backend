import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.infrastructure.models.audit_log import AuditLog
from apps.devices.infrastructure.models.device import WatchlistKeyword


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


def _pair_device(api_client, monitored_tokens, monitor_tokens, fingerprint="fp-kw-1"):
    _auth(api_client, monitored_tokens)
    initiate = api_client.post(
        reverse("device-pair-initiate"),
        {
            "device_name": "KW Phone",
            "platform": "android",
            "device_fingerprint": fingerprint,
        },
        format="json",
    )
    device_id = initiate.data["device_id"]
    code = initiate.data["pairing_code"]
    _auth(api_client, monitor_tokens)
    complete = api_client.post(
        reverse("device-pair-complete"),
        {
            "pairing_code": code.replace("-", ""),
            "consent_scopes": ["sms", "location"],
            "consent_version": "1.0.0",
        },
        format="json",
    )
    assert complete.status_code == status.HTTP_201_CREATED
    return device_id


@pytest.mark.django_db
class TestWatchlistKeywords:
    def test_monitor_crud_and_audit(self, api_client):
        monitored = _register(api_client, "kw-kid@example.com", "KW Kid")
        monitor = _register(api_client, "kw-par@example.com", "KW Par")
        _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-kw-crud"
        )

        _auth(api_client, monitor["tokens"])
        created = api_client.post(
            reverse("keyword-list"),
            {"word": "Emergency"},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED
        assert created.data["word"] == "emergency"
        kid = created.data["id"]

        listed = api_client.get(reverse("keyword-list"))
        assert listed.status_code == status.HTTP_200_OK
        assert len(listed.data["results"]) == 1

        deleted = api_client.delete(
            reverse("keyword-detail", kwargs={"keyword_id": kid})
        )
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert WatchlistKeyword.objects.count() == 0

        actions = set(
            AuditLog.objects.filter(resource_type="keyword").values_list(
                "action", flat=True
            )
        )
        assert "keyword.created" in actions
        assert "keyword.deleted" in actions

    def test_monitored_user_can_list(self, api_client):
        monitored = _register(api_client, "kw-kid2@example.com", "KW Kid 2")
        monitor = _register(api_client, "kw-par2@example.com", "KW Par 2")
        _pair_device(
            api_client, monitored["tokens"], monitor["tokens"], fingerprint="fp-kw-list"
        )

        _auth(api_client, monitor["tokens"])
        api_client.post(
            reverse("keyword-list"), {"word": "help"}, format="json"
        )

        _auth(api_client, monitored["tokens"])
        listed = api_client.get(reverse("keyword-list"))
        assert listed.status_code == status.HTTP_200_OK
        assert {r["word"] for r in listed.data["results"]} == {"help"}
