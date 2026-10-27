import re
import uuid
from dataclasses import dataclass

from django.contrib.auth import authenticate
from django.db import transaction
from django.utils.text import slugify

from apps.accounts.infrastructure.models.user import User
from apps.tenants.infrastructure.models.membership import TenantMembership
from apps.tenants.infrastructure.models.tenant import Tenant
from apps.tenants.application.services.workspace_service import WorkspaceService
from core.domain.exceptions import ConflictError, ValidationError

EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


@dataclass
class RegistrationResult:
    user: User
    tenant: Tenant


class RegistrationService:
    def register(
        self,
        email: str,
        password: str,
        full_name: str,
        tenant_name: str,
    ) -> RegistrationResult:
        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            raise ValidationError("Invalid email address")
        if len(password) < 10:
            raise ValidationError("Password must be at least 10 characters")
        if User.objects.filter(email=email).exists():
            raise ConflictError("Email already registered")

        base_slug = slugify(tenant_name) or "workspace"
        slug = base_slug
        counter = 1
        while Tenant.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=password,
                full_name=full_name,
            )
            tenant = Tenant.objects.create(
                id=uuid.uuid4(),
                name=tenant_name,
                slug=slug,
            )
            TenantMembership.objects.create(
                tenant=tenant,
                user=user,
                role=TenantMembership.Role.OWNER,
            )

        return RegistrationResult(user=user, tenant=tenant)


class AuthenticationService:
    def authenticate_user(self, email: str, password: str) -> User | None:
        email = email.strip().lower()
        user = authenticate(username=email, password=password)
        if user and user.is_active:
            return user
        return None

    def get_user_tenant(self, user: User) -> Tenant | None:
        membership = self.get_user_membership(user)
        return membership.tenant if membership else None

    def get_user_membership(self, user: User) -> TenantMembership | None:
        return (
            TenantMembership.objects.select_related("tenant")
            .filter(user=user, tenant__is_active=True)
            .exclude(tenant__slug__startswith=WorkspaceService.STAGING_SLUG_PREFIX)
            .order_by("created_at")
            .first()
        )

    def get_user_role(self, user: User, tenant: Tenant) -> str | None:
        membership = TenantMembership.objects.filter(user=user, tenant=tenant).first()
        return membership.role if membership else None
