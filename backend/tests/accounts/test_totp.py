"""TOTP 2FA enroll / confirm / login second step / disable."""

import pyotp
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.infrastructure.models.user import User


@pytest.fixture
def api_client():
    return APIClient()


def _register(api_client, email="twofa@example.com"):
    response = api_client.post(
        reverse("auth-register"),
        {
            "email": email,
            "password": "SecurePass123!",
            "full_name": "Two FA",
            "tenant_name": "TwoFA Org",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


def _auth(api_client, tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")


@pytest.mark.django_db
class TestTotpFlow:
    def test_enroll_confirm_login_and_disable(self, api_client):
        data = _register(api_client)
        _auth(api_client, data["tokens"])

        status_resp = api_client.get(reverse("auth-2fa-status"))
        assert status_resp.status_code == status.HTTP_200_OK
        assert status_resp.data["enabled"] is False

        enroll = api_client.post(reverse("auth-2fa-enroll"), {}, format="json")
        assert enroll.status_code == status.HTTP_201_CREATED
        secret = enroll.data["secret"]
        assert enroll.data["otpauth_uri"].startswith("otpauth://totp/")

        code = pyotp.TOTP(secret).now()
        confirm = api_client.post(
            reverse("auth-2fa-confirm"), {"code": code}, format="json"
        )
        assert confirm.status_code == status.HTTP_200_OK
        assert confirm.data["enabled"] is True
        assert len(confirm.data["recovery_codes"]) == 8

        # Logout credentials and login — should require 2FA
        api_client.credentials()
        login = api_client.post(
            reverse("auth-login"),
            {"email": "twofa@example.com", "password": "SecurePass123!"},
            format="json",
        )
        assert login.status_code == status.HTTP_200_OK
        assert login.data["requires_2fa"] is True
        assert "pre_auth_token" in login.data
        assert "access" not in login.data and "tokens" not in login.data

        verify = api_client.post(
            reverse("auth-2fa-verify"),
            {
                "pre_auth_token": login.data["pre_auth_token"],
                "code": pyotp.TOTP(secret).now(),
            },
            format="json",
        )
        assert verify.status_code == status.HTTP_200_OK
        assert "tokens" in verify.data
        assert verify.data["tokens"]["access"]

        _auth(api_client, verify.data["tokens"])
        disable = api_client.post(
            reverse("auth-2fa-disable"),
            {"password": "SecurePass123!"},
            format="json",
        )
        assert disable.status_code == status.HTTP_204_NO_CONTENT
        user = User.objects.get(email="twofa@example.com")
        assert user.totp_enabled is False
        assert user.totp_secret_encrypted == ""

    def test_recovery_code_completes_login(self, api_client):
        data = _register(api_client, "rec@example.com")
        _auth(api_client, data["tokens"])
        enroll = api_client.post(reverse("auth-2fa-enroll"), {}, format="json")
        secret = enroll.data["secret"]
        confirm = api_client.post(
            reverse("auth-2fa-confirm"),
            {"code": pyotp.TOTP(secret).now()},
            format="json",
        )
        recovery = confirm.data["recovery_codes"][0]

        api_client.credentials()
        login = api_client.post(
            reverse("auth-login"),
            {"email": "rec@example.com", "password": "SecurePass123!"},
            format="json",
        )
        verify = api_client.post(
            reverse("auth-2fa-verify"),
            {
                "pre_auth_token": login.data["pre_auth_token"],
                "code": recovery,
            },
            format="json",
        )
        assert verify.status_code == status.HTTP_200_OK

        # Same recovery code cannot be reused
        login2 = api_client.post(
            reverse("auth-login"),
            {"email": "rec@example.com", "password": "SecurePass123!"},
            format="json",
        )
        reuse = api_client.post(
            reverse("auth-2fa-verify"),
            {
                "pre_auth_token": login2.data["pre_auth_token"],
                "code": recovery,
            },
            format="json",
        )
        assert reuse.status_code == status.HTTP_403_FORBIDDEN
