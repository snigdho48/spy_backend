from __future__ import annotations

import re

from django.db.models import QuerySet

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.accounts.infrastructure.models.user import User
from apps.audit.application.services.audit_service import AuditService
from apps.devices.application.services.safe_zone_service import MANAGE_ROLES
from apps.devices.infrastructure.models.device import Device, WatchlistKeyword
from apps.tenants.application.services.workspace_service import WorkspaceService
from apps.tenants.infrastructure.models.membership import TenantMembership
from core.domain.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)

MAX_WORD_LEN = 64
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class KeywordService:
    def list_for_user(self, user: User) -> QuerySet[WatchlistKeyword]:
        membership = AuthenticationService().get_user_membership(user)
        owned = Device.objects.filter(
            owner=user, status=Device.Status.ACTIVE
        ).only("tenant_id")
        owned_tenant_ids = set(owned.values_list("tenant_id", flat=True))

        monitored_elsewhere = bool(owned_tenant_ids) and (
            membership is None
            or membership.tenant_id not in owned_tenant_ids
            or WorkspaceService.is_staging_tenant(membership.tenant)
        )
        if monitored_elsewhere:
            return (
                WatchlistKeyword.objects.filter(tenant_id__in=owned_tenant_ids)
                .select_related("created_by")
                .order_by("word")
            )

        if (
            membership
            and membership.role in MANAGE_ROLES
            and not WorkspaceService.is_staging_tenant(membership.tenant)
        ):
            return (
                WatchlistKeyword.objects.filter(tenant=membership.tenant)
                .select_related("created_by")
                .order_by("word")
            )

        raise PermissionDeniedError(
            "Only workspace monitors or monitored device owners can list keywords"
        )

    def create(self, *, user: User, word: str) -> WatchlistKeyword:
        membership = self._require_manage_membership(user)
        cleaned = self._clean_word(word)
        if WatchlistKeyword.objects.filter(
            tenant=membership.tenant, word__iexact=cleaned
        ).exists():
            raise ValidationError("Keyword already exists")

        row = WatchlistKeyword.objects.create(
            tenant=membership.tenant,
            word=cleaned,
            created_by=user,
        )
        AuditService().log(
            tenant=membership.tenant,
            actor=user,
            action="keyword.created",
            resource_type="keyword",
            resource_id=row.id,
            metadata={"word": row.word},
        )
        return row

    def delete(self, *, user: User, keyword_id) -> None:
        membership = self._require_manage_membership(user)
        row = WatchlistKeyword.objects.filter(
            tenant=membership.tenant, pk=keyword_id
        ).first()
        if not row:
            raise EntityNotFoundError("Keyword not found")
        word = row.word
        row_id = row.id
        row.delete()
        AuditService().log(
            tenant=membership.tenant,
            actor=user,
            action="keyword.deleted",
            resource_type="keyword",
            resource_id=row_id,
            metadata={"word": word},
        )

    def _require_manage_membership(self, user: User) -> TenantMembership:
        membership = AuthenticationService().get_user_membership(user)
        if (
            not membership
            or membership.role not in MANAGE_ROLES
            or WorkspaceService.is_staging_tenant(membership.tenant)
        ):
            raise PermissionDeniedError(
                "Only workspace owners, admins or monitors can manage keywords"
            )
        return membership

    def _clean_word(self, word: str) -> str:
        cleaned = _CONTROL.sub("", (word or "").strip().lower())
        if not cleaned:
            raise ValidationError("word is required")
        if len(cleaned) > MAX_WORD_LEN:
            raise ValidationError(f"word cannot exceed {MAX_WORD_LEN} characters")
        if " " in cleaned and len(cleaned.split()) > 4:
            raise ValidationError("word phrases cannot exceed 4 tokens")
        return cleaned
