"""Refresh-token session list / revoke / logout integration."""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.infrastructure.models.refresh_token import RefreshTokenRecord


@pytest.fixture
def api_client():
    return APIClient()


def _register(api_client, email="sess@example.com"):
    response = api_client.post(
        reverse("auth-register"),
        {
            "email": email,
            "password": "SecurePass123!",
            "full_name": "Sess",
            "tenant_name": "SessOrg",
            "device_label": "Test Phone",
        },
        format="json",
        HTTP_USER_AGENT="SpyLove/1.0 (Android)",
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


def _auth(api_client, tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")


@pytest.mark.django_db
class TestSessions:
    def test_register_creates_session_and_list_marks_current(self, api_client):
        data = _register(api_client)
        _auth(api_client, data["tokens"])
        assert RefreshTokenRecord.objects.filter(
            user_id=data["user"]["id"], revoked_at__isnull=True
        ).count() == 1

        listed = api_client.get(
            reverse("auth-sessions"),
            {"refresh": data["tokens"]["refresh"]},
        )
        assert listed.status_code == status.HTTP_200_OK
        assert len(listed.data["sessions"]) == 1
        sess = listed.data["sessions"][0]
        assert sess["is_current"] is True
        assert sess["device_label"] == "Test Phone"

    def test_revoke_others_and_logout(self, api_client):
        data = _register(api_client, "sess2@example.com")
        refresh1 = data["tokens"]["refresh"]

        # Second login creates another session
        login = api_client.post(
            reverse("auth-login"),
            {
                "email": "sess2@example.com",
                "password": "SecurePass123!",
                "device_label": "Laptop",
            },
            format="json",
            HTTP_USER_AGENT="Mozilla/5.0",
        )
        assert login.status_code == status.HTTP_200_OK
        refresh2 = login.data["refresh"]
        access2 = login.data["access"]
        _auth(api_client, {"access": access2})

        listed = api_client.get(
            reverse("auth-sessions"), {"refresh": refresh2}
        )
        assert len(listed.data["sessions"]) == 2

        revoked = api_client.post(
            reverse("auth-sessions-revoke-others"),
            {"refresh": refresh2},
            format="json",
        )
        assert revoked.status_code == status.HTTP_200_OK
        assert revoked.data["revoked"] == 1

        listed2 = api_client.get(
            reverse("auth-sessions"), {"refresh": refresh2}
        )
        assert len(listed2.data["sessions"]) == 1
        assert listed2.data["sessions"][0]["is_current"] is True

        # Logout current
        out = api_client.post(
            reverse("auth-logout"), {"refresh": refresh2}, format="json"
        )
        assert out.status_code == status.HTTP_204_NO_CONTENT
        assert (
            RefreshTokenRecord.objects.filter(
                user_id=data["user"]["id"], revoked_at__isnull=True
            ).count()
            == 0
        )
        # old refresh1 already revoked by revoke-others
        assert RefreshTokenRecord.objects.filter(
            jti__isnull=False
        ).exists()

    def test_revoke_single_session(self, api_client):
        data = _register(api_client, "sess3@example.com")
        _auth(api_client, data["tokens"])
        login = api_client.post(
            reverse("auth-login"),
            {"email": "sess3@example.com", "password": "SecurePass123!"},
            format="json",
        )
        _auth(api_client, {"access": login.data["access"]})
        listed = api_client.get(
            reverse("auth-sessions"), {"refresh": login.data["refresh"]}
        )
        other = next(s for s in listed.data["sessions"] if not s["is_current"])
        resp = api_client.delete(
            reverse("auth-session-revoke", kwargs={"session_id": other["id"]})
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        listed2 = api_client.get(
            reverse("auth-sessions"), {"refresh": login.data["refresh"]}
        )
        assert len(listed2.data["sessions"]) == 1
