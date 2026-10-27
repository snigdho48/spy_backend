from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.tenants.application.services.workspace_service import (
    SubscriptionService,
    WorkspaceService,
)
from apps.tenants.domain.plan_catalog import list_plans, plan_to_dict
from apps.tenants.presentation.serializers.tenant_serializers import (
    SubscribeSerializer,
    WorkspaceCreateSerializer,
)
from apps.tenants.infrastructure.models.membership import TenantMembership
from core.domain.exceptions import EntityNotFoundError, PermissionDeniedError


class TenantMixin:
    def get_membership(self):
        if not hasattr(self, "_cached_membership"):
            self._cached_membership = AuthenticationService().get_user_membership(
                self.request.user
            )
        return self._cached_membership

    def get_tenant(self):
        membership = self.get_membership()
        if not membership:
            raise EntityNotFoundError("No active tenant membership")
        return membership.tenant


class PlanListView(APIView):
    def get(self, request):
        plans = [plan_to_dict(p) for p in list_plans()]
        return Response({"plans": plans})


class CurrentSubscriptionView(APIView):
    def get(self, request):
        membership = AuthenticationService().get_user_membership(request.user)
        if not membership:
            return Response(
                {
                    "has_workspace": False,
                    "needs_workspace": True,
                    "subscription": None,
                }
            )

        tenant = membership.tenant
        subscription = SubscriptionService().get_tenant_subscription(tenant)
        return Response(
            {
                "has_workspace": True,
                "needs_workspace": False,
                "tenant": {
                    "id": tenant.id,
                    "name": tenant.name,
                    "slug": tenant.slug,
                },
                "role": membership.role,
                "subscription": subscription,
            }
        )


class SubscribeView(TenantMixin, APIView):
    # TODO(billing): there is no payment integration yet. Plan changes are
    # restricted to workspace owners/admins; add checkout/payment verification
    # before enabling paid plans in production.
    PLAN_CHANGE_ROLES = (
        TenantMembership.Role.OWNER,
        TenantMembership.Role.ADMIN,
    )

    def post(self, request):
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = self.get_membership()
        if not membership:
            raise EntityNotFoundError("No active tenant membership")
        if membership.role not in self.PLAN_CHANGE_ROLES:
            raise PermissionDeniedError(
                "Only workspace owners or admins can change the plan"
            )
        tenant = membership.tenant
        tenant = SubscriptionService().subscribe(
            tenant=tenant,
            plan_code=serializer.validated_data["plan_code"],
        )
        subscription = SubscriptionService().get_tenant_subscription(tenant)
        return Response({"subscription": subscription})


class WorkspaceCreateView(APIView):
    def post(self, request):
        serializer = WorkspaceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = WorkspaceService().create_workspace(
            user=request.user,
            name=serializer.validated_data["name"],
        )
        subscription = SubscriptionService().get_tenant_subscription(tenant)
        membership = AuthenticationService().get_user_membership(request.user)
        return Response(
            {
                "tenant": {
                    "id": tenant.id,
                    "name": tenant.name,
                    "slug": tenant.slug,
                },
                "role": membership.role if membership else "owner",
                "subscription": subscription,
            },
            status=status.HTTP_201_CREATED,
        )
