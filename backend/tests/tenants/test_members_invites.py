"""Workspace members + invite API coverage."""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.infrastructure.models.user import User
from apps.tenants.infrastructure.models.invite import TenantInvite
from apps.tenants.infrastructure.models.membership import TenantMembership
from apps.tenants.infrastructure.models.tenant import Tenant


@pytest.fixture
def api_client():
    return APIClient()


def _register(api_client, email, tenant_name, full_name=None):
    response = api_client.post(
        reverse("auth-register"),
        {
            "email": email,
            "password": "SecurePass123!",
            "full_name": full_name or email.split("@")[0],
            "tenant_name": tenant_name,
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return response.data


def _auth(api_client, tokens):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")


@pytest.mark.django_db
class TestMembersAndInvites:
    def test_owner_lists_self_and_invites_member(self, api_client):
        owner = _register(api_client, "owner@example.com", "FamilyHQ")
        _auth(api_client, owner["tokens"])

        listed = api_client.get(reverse("tenant-members"))
        assert listed.status_code == status.HTTP_200_OK
        assert len(listed.data["members"]) == 1
        assert listed.data["members"][0]["role"] == "owner"

        # Invitee must already have an account (accept requires auth).
        invitee = _register(api_client, "invitee@example.com", "OtherOrg")
        # Switch back to owner
        _auth(api_client, owner["tokens"])

        created = api_client.post(
            reverse("tenant-invites"),
            {"email": "invitee@example.com", "role": "monitor"},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.data
        invite = created.data["invite"]
        assert invite["email"] == "invitee@example.com"
        assert invite["role"] == "monitor"
        assert invite["token"]
        assert "invite_link" in invite
        raw_token = invite["token"]

        # Viewer/monitor cannot manage — invitee not yet in workspace.
        pending = api_client.get(reverse("tenant-invites"))
        assert pending.status_code == status.HTTP_200_OK
        assert len(pending.data["invites"]) == 1

        # Accept as invitee (must leave other workspace first — conflict)
        _auth(api_client, invitee["tokens"])
        conflict = api_client.post(
            reverse("tenant-invite-accept"),
            {"token": raw_token},
            format="json",
        )
        assert conflict.status_code == status.HTTP_409_CONFLICT

        # Remove invitee from their own workspace so they can join.
        TenantMembership.objects.filter(user_id=invitee["user"]["id"]).delete()
        Tenant.objects.filter(pk=invitee["tenant"]["id"]).delete()

        accepted = api_client.post(
            reverse("tenant-invite-accept"),
            {"token": raw_token},
            format="json",
        )
        assert accepted.status_code == status.HTTP_200_OK, accepted.data
        assert accepted.data["role"] == "monitor"

        _auth(api_client, owner["tokens"])
        members = api_client.get(reverse("tenant-members"))
        assert len(members.data["members"]) == 2

    def test_cannot_demote_last_owner(self, api_client):
        owner = _register(api_client, "solo@example.com", "SoloOrg")
        _auth(api_client, owner["tokens"])
        membership_id = TenantMembership.objects.get(
            user_id=owner["user"]["id"]
        ).id
        resp = api_client.patch(
            reverse("tenant-member-detail", kwargs={"membership_id": membership_id}),
            {"role": "admin"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_admin_cannot_remove_owner(self, api_client):
        owner_data = _register(api_client, "own2@example.com", "OrgTwo")
        tenant_id = owner_data["tenant"]["id"]
        owner_user = User.objects.get(pk=owner_data["user"]["id"])

        admin_user = User.objects.create_user(
            email="admin2@example.com",
            password="SecurePass123!",
            full_name="Admin",
        )
        admin_m = TenantMembership.objects.create(
            tenant_id=tenant_id,
            user=admin_user,
            role=TenantMembership.Role.ADMIN,
        )
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(admin_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        owner_m = TenantMembership.objects.get(user=owner_user, tenant_id=tenant_id)
        resp = api_client.delete(
            reverse("tenant-member-detail", kwargs={"membership_id": owner_m.id})
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

        # Admin can change a monitor's role
        mon = User.objects.create_user(
            email="mon@example.com", password="SecurePass123!", full_name="Mon"
        )
        mon_m = TenantMembership.objects.create(
            tenant_id=tenant_id,
            user=mon,
            role=TenantMembership.Role.MONITOR,
        )
        changed = api_client.patch(
            reverse("tenant-member-detail", kwargs={"membership_id": mon_m.id}),
            {"role": "viewer"},
            format="json",
        )
        assert changed.status_code == status.HTTP_200_OK
        assert changed.data["member"]["role"] == "viewer"

        # And remove them
        removed = api_client.delete(
            reverse("tenant-member-detail", kwargs={"membership_id": mon_m.id})
        )
        assert removed.status_code == status.HTTP_204_NO_CONTENT
        assert not TenantMembership.objects.filter(pk=mon_m.id).exists()
        # cleanup unused var
        assert admin_m.role == TenantMembership.Role.ADMIN

    def test_decline_invite(self, api_client):
        owner = _register(api_client, "o3@example.com", "OrgThree")
        _auth(api_client, owner["tokens"])
        invitee = _register(api_client, "dec@example.com", "DecOrg")
        _auth(api_client, owner["tokens"])
        created = api_client.post(
            reverse("tenant-invites"),
            {"email": "dec@example.com", "role": "viewer"},
            format="json",
        )
        token = created.data["invite"]["token"]
        _auth(api_client, invitee["tokens"])
        declined = api_client.post(
            reverse("tenant-invite-decline"),
            {"token": token},
            format="json",
        )
        assert declined.status_code == status.HTTP_204_NO_CONTENT
        inv = TenantInvite.objects.get(email="dec@example.com")
        assert inv.status == TenantInvite.Status.DECLINED

    def test_monitor_cannot_invite(self, api_client):
        owner = _register(api_client, "o4@example.com", "OrgFour")
        tenant_id = owner["tenant"]["id"]
        mon = User.objects.create_user(
            email="mon4@example.com", password="SecurePass123!", full_name="M"
        )
        TenantMembership.objects.create(
            tenant_id=tenant_id, user=mon, role=TenantMembership.Role.MONITOR
        )
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(mon)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        resp = api_client.post(
            reverse("tenant-invites"),
            {"email": "x@example.com", "role": "viewer"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
