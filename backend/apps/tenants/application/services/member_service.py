"""Workspace member and invite management."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.infrastructure.models.user import User
from apps.tenants.application.services.email_service import send_invite_email
from apps.tenants.application.services.workspace_service import (
    SubscriptionService,
    WorkspaceService,
)
from apps.tenants.domain.plan_catalog import get_plan
from apps.tenants.infrastructure.models.invite import TenantInvite
from apps.tenants.infrastructure.models.membership import TenantMembership
from apps.tenants.infrastructure.models.tenant import Tenant
from core.domain.exceptions import (
    ConflictError,
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)

MANAGE_ROLES = (
    TenantMembership.Role.OWNER,
    TenantMembership.Role.ADMIN,
)

# Invites may grant these roles (never owner via invite).
INVITABLE_ROLES = (
    TenantMembership.Role.ADMIN,
    TenantMembership.Role.MONITOR,
    TenantMembership.Role.VIEWER,
)

ASSIGNABLE_ROLES = (
    TenantMembership.Role.OWNER,
    TenantMembership.Role.ADMIN,
    TenantMembership.Role.MONITOR,
    TenantMembership.Role.VIEWER,
)

INVITE_TTL_DAYS = 7


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _invite_link(raw_token: str) -> str:
    base = (getattr(settings, "APP_PUBLIC_URL", "") or "").rstrip("/")
    if not base:
        base = "https://app.example.com"
    return f"{base}/invite?token={raw_token}"


class MemberService:
    def ensure_can_manage(self, *, actor: User, tenant: Tenant) -> TenantMembership:
        membership = TenantMembership.objects.filter(user=actor, tenant=tenant).first()
        if not membership or membership.role not in MANAGE_ROLES:
            raise PermissionDeniedError("Only owners and admins can manage members")
        return membership

    def _active_memberships(self, tenant: Tenant) -> QuerySet[TenantMembership]:
        return TenantMembership.objects.filter(tenant=tenant).select_related("user")

    def list_members(self, *, actor: User, tenant: Tenant) -> list[dict]:
        # Any workspace member may list (read-only for non-managers).
        if not TenantMembership.objects.filter(user=actor, tenant=tenant).exists():
            raise PermissionDeniedError("Not a member of this workspace")
        rows = []
        for m in self._active_memberships(tenant).order_by("created_at"):
            rows.append(
                {
                    "id": str(m.id),
                    "user": {
                        "id": m.user_id,
                        "email": m.user.email,
                        "full_name": m.user.full_name,
                    },
                    "role": m.role,
                    "created_at": m.created_at.isoformat(),
                }
            )
        return rows

    def _owner_count(self, tenant: Tenant) -> int:
        return TenantMembership.objects.filter(
            tenant=tenant, role=TenantMembership.Role.OWNER
        ).count()

    def _ensure_member_capacity(self, tenant: Tenant) -> None:
        plan = get_plan(tenant.plan) or get_plan(Tenant.Plan.FREE)
        if not plan:
            return
        current = TenantMembership.objects.filter(tenant=tenant).count()
        # Pending invites also reserve a seat.
        pending = TenantInvite.objects.filter(
            tenant=tenant, status=TenantInvite.Status.PENDING
        ).count()
        if current + pending >= plan.max_members:
            raise ValidationError(
                f"Member limit reached ({plan.max_members}) for {plan.name} plan"
            )

    def invite(
        self,
        *,
        actor: User,
        tenant: Tenant,
        email: str,
        role: str,
    ) -> dict:
        self.ensure_can_manage(actor=actor, tenant=tenant)
        email = email.strip().lower()
        if role not in INVITABLE_ROLES:
            raise ValidationError("Invalid invite role")
        if TenantMembership.objects.filter(tenant=tenant, user__email=email).exists():
            raise ConflictError("User is already a member of this workspace")

        existing = TenantInvite.objects.filter(
            tenant=tenant, email=email, status=TenantInvite.Status.PENDING
        ).first()
        if existing and existing.expires_at > timezone.now():
            raise ConflictError("A pending invite already exists for this email")

        self._ensure_member_capacity(tenant)

        raw_token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(days=INVITE_TTL_DAYS)
        with transaction.atomic():
            if existing:
                existing.status = TenantInvite.Status.REVOKED
                existing.responded_at = timezone.now()
                existing.save(update_fields=["status", "responded_at", "updated_at"])
            invite = TenantInvite.objects.create(
                tenant=tenant,
                email=email,
                role=role,
                invited_by=actor,
                token_hash=_hash_token(raw_token),
                expires_at=expires_at,
            )

        link = _invite_link(raw_token)
        emailed = send_invite_email(
            to_email=email,
            tenant_name=tenant.name,
            invite_link=link,
            role=role,
        )
        return {
            "id": str(invite.id),
            "email": invite.email,
            "role": invite.role,
            "status": invite.status,
            "expires_at": invite.expires_at.isoformat(),
            "invite_link": link,
            "email_sent": emailed,
            "token": raw_token,  # one-time reveal for share/copy; not stored plaintext
        }

    def list_pending_invites(self, *, actor: User, tenant: Tenant) -> list[dict]:
        self.ensure_can_manage(actor=actor, tenant=tenant)
        now = timezone.now()
        out = []
        for inv in TenantInvite.objects.filter(
            tenant=tenant, status=TenantInvite.Status.PENDING
        ).order_by("-created_at"):
            expired = inv.expires_at <= now
            if expired:
                inv.status = TenantInvite.Status.EXPIRED
                inv.save(update_fields=["status", "updated_at"])
                continue
            out.append(
                {
                    "id": str(inv.id),
                    "email": inv.email,
                    "role": inv.role,
                    "status": inv.status,
                    "expires_at": inv.expires_at.isoformat(),
                    "created_at": inv.created_at.isoformat(),
                }
            )
        return out

    def revoke_invite(self, *, actor: User, tenant: Tenant, invite_id) -> None:
        self.ensure_can_manage(actor=actor, tenant=tenant)
        invite = TenantInvite.objects.filter(pk=invite_id, tenant=tenant).first()
        if not invite:
            raise EntityNotFoundError("Invite not found")
        if invite.status != TenantInvite.Status.PENDING:
            raise ValidationError("Only pending invites can be revoked")
        invite.status = TenantInvite.Status.REVOKED
        invite.responded_at = timezone.now()
        invite.save(update_fields=["status", "responded_at", "updated_at"])

    def _get_pending_by_token(self, raw_token: str) -> TenantInvite:
        token_hash = _hash_token(raw_token.strip())
        invite = (
            TenantInvite.objects.select_related("tenant")
            .filter(token_hash=token_hash)
            .first()
        )
        if not invite:
            raise EntityNotFoundError("Invite not found")
        if invite.status != TenantInvite.Status.PENDING:
            raise ValidationError(f"Invite is {invite.status}")
        if invite.expires_at <= timezone.now():
            invite.status = TenantInvite.Status.EXPIRED
            invite.save(update_fields=["status", "updated_at"])
            raise ValidationError("Invite has expired")
        return invite

    def accept_invite(self, *, user: User, raw_token: str) -> dict:
        invite = self._get_pending_by_token(raw_token)
        if user.email.strip().lower() != invite.email.lower():
            raise PermissionDeniedError(
                "This invite was sent to a different email address"
            )
        if TenantMembership.objects.filter(user=user, tenant=invite.tenant).exists():
            raise ConflictError("You are already a member of this workspace")

        # Users may only belong to one active non-staging workspace.
        other = (
            TenantMembership.objects.filter(user=user, tenant__is_active=True)
            .exclude(tenant__slug__startswith=WorkspaceService.STAGING_SLUG_PREFIX)
            .exclude(tenant_id=invite.tenant_id)
            .exists()
        )
        if other:
            raise ConflictError(
                "Leave your current workspace before accepting another invite"
            )

        with transaction.atomic():
            membership = TenantMembership.objects.create(
                tenant=invite.tenant,
                user=user,
                role=invite.role,
            )
            invite.status = TenantInvite.Status.ACCEPTED
            invite.accepted_by = user
            invite.responded_at = timezone.now()
            invite.save(
                update_fields=[
                    "status",
                    "accepted_by",
                    "responded_at",
                    "updated_at",
                ]
            )

        return {
            "membership_id": str(membership.id),
            "tenant": {
                "id": invite.tenant_id,
                "name": invite.tenant.name,
                "slug": invite.tenant.slug,
            },
            "role": membership.role,
        }

    def decline_invite(self, *, user: User, raw_token: str) -> None:
        invite = self._get_pending_by_token(raw_token)
        if user.email.strip().lower() != invite.email.lower():
            raise PermissionDeniedError(
                "This invite was sent to a different email address"
            )
        invite.status = TenantInvite.Status.DECLINED
        invite.responded_at = timezone.now()
        invite.save(update_fields=["status", "responded_at", "updated_at"])

    def change_role(
        self,
        *,
        actor: User,
        tenant: Tenant,
        membership_id,
        new_role: str,
    ) -> dict:
        actor_membership = self.ensure_can_manage(actor=actor, tenant=tenant)
        if new_role not in ASSIGNABLE_ROLES:
            raise ValidationError("Invalid role")

        target = (
            TenantMembership.objects.select_related("user")
            .filter(pk=membership_id, tenant=tenant)
            .first()
        )
        if not target:
            raise EntityNotFoundError("Member not found")

        # Only owners may grant/revoke OWNER.
        if new_role == TenantMembership.Role.OWNER and actor_membership.role != (
            TenantMembership.Role.OWNER
        ):
            raise PermissionDeniedError("Only an owner can assign the owner role")
        if (
            target.role == TenantMembership.Role.OWNER
            and new_role != TenantMembership.Role.OWNER
            and self._owner_count(tenant) <= 1
        ):
            raise ValidationError("Cannot demote the last owner")

        # Admins cannot demote/change owners.
        if (
            target.role == TenantMembership.Role.OWNER
            and actor_membership.role != TenantMembership.Role.OWNER
        ):
            raise PermissionDeniedError("Admins cannot change an owner's role")

        target.role = new_role
        target.save(update_fields=["role", "updated_at"])
        return {
            "id": str(target.id),
            "user": {
                "id": target.user_id,
                "email": target.user.email,
                "full_name": target.user.full_name,
            },
            "role": target.role,
        }

    def remove_member(
        self,
        *,
        actor: User,
        tenant: Tenant,
        membership_id,
    ) -> None:
        actor_membership = self.ensure_can_manage(actor=actor, tenant=tenant)
        target = TenantMembership.objects.filter(pk=membership_id, tenant=tenant).first()
        if not target:
            raise EntityNotFoundError("Member not found")
        if target.user_id == actor.id:
            raise ValidationError("Use leave workspace to remove yourself")
        if target.role == TenantMembership.Role.OWNER:
            if actor_membership.role != TenantMembership.Role.OWNER:
                raise PermissionDeniedError("Admins cannot remove an owner")
            if self._owner_count(tenant) <= 1:
                raise ValidationError("Cannot remove the last owner")
        target.delete()
