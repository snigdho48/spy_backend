from rest_framework import generics, serializers

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.audit.infrastructure.models.audit_log import AuditLog
from apps.tenants.infrastructure.models.membership import TenantMembership
from core.domain.exceptions import EntityNotFoundError, PermissionDeniedError


class AuditLogSerializer(serializers.ModelSerializer):
    actor_id = serializers.UUIDField(source="actor.id", allow_null=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "metadata",
            "ip_address",
            "created_at",
        ]


class AuditLogListView(generics.ListAPIView):
    serializer_class = AuditLogSerializer

    # Audit logs expose actor IPs and activity: owners, admins and monitors may
    # read them (product decision); viewers are forbidden.
    AUDIT_ROLES = (
        TenantMembership.Role.OWNER,
        TenantMembership.Role.ADMIN,
        TenantMembership.Role.MONITOR,
    )

    def get_queryset(self):
        auth = AuthenticationService()
        membership = auth.get_user_membership(self.request.user)
        if not membership:
            raise EntityNotFoundError("No active tenant membership")
        if membership.role not in self.AUDIT_ROLES:
            raise PermissionDeniedError(
                "Only workspace owners, admins or monitors can view the audit log"
            )
        tenant = membership.tenant

        qs = AuditLog.objects.filter(tenant=tenant).select_related("actor")
        actor_id = self.request.query_params.get("actor_id")
        if actor_id:
            qs = qs.filter(actor_id=actor_id)
        action = self.request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)
        return qs.order_by("-created_at")
