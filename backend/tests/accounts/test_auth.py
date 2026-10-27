import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def registered_user(api_client):
    response = api_client.post(
        reverse("auth-register"),
        {
            "email": "test@example.com",
            "password": "SecurePass123!",
            "full_name": "Test User",
            "tenant_name": "Test Org",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.data


@pytest.mark.django_db
class TestAuthAPI:
    def test_register_creates_user_and_tenant(self, api_client):
        response = api_client.post(
            reverse("auth-register"),
            {
                "email": "new@example.com",
                "password": "SecurePass123!",
                "full_name": "New User",
                "tenant_name": "New Org",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "tokens" in response.data
        assert response.data["user"]["email"] == "new@example.com"
        assert response.data["tenant"]["name"] == "New Org"

    def test_login_returns_tokens(self, api_client, registered_user):
        response = api_client.post(
            reverse("auth-login"),
            {"email": "test@example.com", "password": "SecurePass123!"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data

    def test_me_requires_auth(self, api_client):
        response = api_client.get(reverse("auth-me"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_me_returns_user(self, api_client, registered_user):
        api_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {registered_user['tokens']['access']}"
        )
        response = api_client.get(reverse("auth-me"))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["user"]["email"] == "test@example.com"


@pytest.mark.django_db
class TestGoogleAuthAPI:
    _google_payload = {
        "sub": "google-user-123",
        "email": "google@example.com",
        "name": "Google User",
    }
    _verify_path = (
        "apps.accounts.application.services.google_auth_service"
        ".GoogleAuthService.verify_id_token"
    )

    @patch(_verify_path)
    def test_google_login_new_user_requires_tenant(self, mock_verify, api_client):
        mock_verify.return_value = self._google_payload
        response = api_client.post(
            reverse("auth-google"),
            {"id_token": "fake-token"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"]["code"] == "tenant_required"

    @patch(_verify_path)
    def test_google_login_creates_user(self, mock_verify, api_client):
        mock_verify.return_value = self._google_payload
        response = api_client.post(
            reverse("auth-google"),
            {"id_token": "fake-token", "tenant_name": "Google Org"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["user"]["email"] == "google@example.com"
        assert response.data["auth_methods"]["has_google"] is True
        assert response.data["auth_methods"]["has_password"] is False

    @patch(_verify_path)
    def test_google_login_links_existing_email_user(
        self, mock_verify, api_client, registered_user
    ):
        mock_verify.return_value = {
            "sub": "google-user-456",
            "email": "test@example.com",
            "name": "Test User",
        }
        response = api_client.post(
            reverse("auth-google"),
            {"id_token": "fake-token"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["auth_methods"]["has_google"] is True
        assert response.data["auth_methods"]["has_password"] is True

    @patch(_verify_path)
    def test_set_password_for_google_user(self, mock_verify, api_client):
        mock_verify.return_value = self._google_payload
        signup = api_client.post(
            reverse("auth-google"),
            {"id_token": "fake-token", "tenant_name": "Google Org"},
            format="json",
        )
        api_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {signup.data['tokens']['access']}"
        )
        response = api_client.post(
            reverse("auth-set-password"),
            {"password": "SecurePass123!"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["auth_methods"]["has_password"] is True

    @patch(_verify_path)
    def test_link_google_for_email_user(self, mock_verify, api_client, registered_user):
        mock_verify.return_value = {
            "sub": "google-user-789",
            "email": "test@example.com",
            "name": "Test User",
        }
        api_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {registered_user['tokens']['access']}"
        )
        response = api_client.post(
            reverse("auth-link-google"),
            {"id_token": "fake-token"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["auth_methods"]["has_google"] is True
        assert response.data["auth_methods"]["has_password"] is True


@pytest.mark.django_db
class TestHealthAPI:
    def test_health_endpoint(self, api_client):
        response = api_client.get("/health/")
        assert response.status_code == status.HTTP_200_OK
        assert "status" in response.data
