from uuid import UUID

from apps.accounts.infrastructure.models.user import User
from apps.audit.infrastructure.models.audit_log import AuditLog
from apps.tenants.infrastructure.models.tenant import Tenant
from core.middleware.audit import get_audit_context


class AuditService:
    def log(
        self,
        *,
        tenant: Tenant,
        actor: User | None,
        action: str,
        resource_type: str,
        resource_id: UUID,
        metadata: dict | None = None,
    ) -> AuditLog:
        ctx = get_audit_context()
        return AuditLog.objects.create(
            tenant=tenant,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata or {},
            ip_address=ctx.get("ip_address"),
            user_agent=ctx.get("user_agent", ""),
        )
