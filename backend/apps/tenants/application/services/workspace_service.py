import uuid

from django.db import transaction
from django.utils.text import slugify

from apps.accounts.infrastructure.models.user import User
from apps.tenants.domain.plan_catalog import get_plan
from apps.tenants.infrastructure.models.membership import TenantMembership
from apps.tenants.infrastructure.models.tenant import Tenant
from core.domain.exceptions import ConflictError, EntityNotFoundError, ValidationError


class WorkspaceService:
    """Creates a workspace (tenant + owner membership) for users without one."""

    STAGING_SLUG_PREFIX = "device-staging-"

    @classmethod
    def is_staging_tenant(cls, tenant: Tenant) -> bool:
        return tenant.slug.startswith(cls.STAGING_SLUG_PREFIX)

    def get_or_create_staging_tenant(self, user: User) -> Tenant:
        """Personal staging tenant for devices awaiting monitor approval.

        Monitored devices may use a separate account without a monitoring workspace.
        Pending devices are stored here until an approver completes pairing.
        """
        membership = (
            TenantMembership.objects.select_related("tenant")
            .filter(
                user=user,
                tenant__slug=f"device-staging-{user.id}",
            )
            .first()
        )
        if membership:
            return membership.tenant

        slug = f"device-staging-{user.id}"
        with transaction.atomic():
            tenant = Tenant.objects.create(
                id=uuid.uuid4(),
                name="Device pairing",
                slug=slug,
                plan=Tenant.Plan.FREE,
                is_active=True,
            )
            TenantMembership.objects.create(
                tenant=tenant,
                user=user,
                role=TenantMembership.Role.OWNER,
            )
        return tenant

    def create_workspace(self, *, user: User, name: str) -> Tenant:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Workspace name is required")

        if TenantMembership.objects.filter(user=user, tenant__is_active=True).exists():
            raise ConflictError("You already belong to an active workspace")

        base_slug = slugify(name) or "workspace"
        slug = base_slug
        counter = 1
        while Tenant.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        with transaction.atomic():
            tenant = Tenant.objects.create(
                id=uuid.uuid4(),
                name=name,
                slug=slug,
                plan=Tenant.Plan.FREE,
                is_active=True,
            )
            TenantMembership.objects.create(
                tenant=tenant,
                user=user,
                role=TenantMembership.Role.OWNER,
            )
        return tenant


class SubscriptionService:
    def get_tenant_subscription(self, tenant: Tenant) -> dict:
        plan = get_plan(tenant.plan)
        if not plan:
            plan = get_plan(Tenant.Plan.FREE)

        return {
            "plan_code": tenant.plan,
            "plan_name": plan.name if plan else tenant.plan,
            "is_active": tenant.is_active,
            "price_monthly_usd": plan.price_monthly_usd if plan else 0,
            "max_devices": plan.max_devices if plan else 2,
            "max_members": plan.max_members if plan else 2,
            "event_retention_days": plan.event_retention_days if plan else 7,
            "features": list(plan.features) if plan else [],
        }

    def subscribe(self, *, tenant: Tenant, plan_code: str) -> Tenant:
        plan = get_plan(plan_code)
        if not plan:
            raise ValidationError(f"Unknown plan: {plan_code}")

        tenant.plan = plan_code
        tenant.is_active = True
        tenant.save(update_fields=["plan", "is_active", "updated_at"])
        return tenant

    def ensure_tenant_can_add_device(self, tenant: Tenant) -> None:
        from apps.devices.infrastructure.models.device import Device

        plan = get_plan(tenant.plan) or get_plan(Tenant.Plan.FREE)
        if not plan:
            return

        active_count = Device.objects.filter(
            tenant=tenant,
            status__in=[Device.Status.PENDING, Device.Status.ACTIVE],
        ).count()
        if active_count >= plan.max_devices:
            raise ValidationError(
                f"Device limit reached ({plan.max_devices}) for {plan.name} plan. "
                "Upgrade your subscription to add more devices."
            )

        if not tenant.is_active:
            raise ValidationError(
                "Workspace subscription is inactive. Choose a plan to continue."
            )
