import uuid
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils.text import slugify
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from apps.accounts.application.services.auth_service import RegistrationResult
from apps.accounts.infrastructure.models.social_account import SocialAccount
from apps.accounts.infrastructure.models.user import User
from apps.tenants.infrastructure.models.membership import TenantMembership
from apps.tenants.infrastructure.models.tenant import Tenant
from core.domain.exceptions import ConflictError, ValidationError


@dataclass
class GoogleAuthResult:
    user: User
    tenant: Tenant | None
    role: str | None
    is_new_user: bool


class GoogleAuthService:
    def verify_id_token(self, raw_token: str) -> dict:
        client_ids = getattr(settings, "GOOGLE_CLIENT_IDS", [])
        if not client_ids:
            raise ValidationError("Google Sign-In is not configured on the server")

        last_error: Exception | None = None
        for client_id in client_ids:
            try:
                return id_token.verify_oauth2_token(
                    raw_token,
                    google_requests.Request(),
                    client_id,
                )
            except ValueError as exc:
                last_error = exc
                continue

        raise ValidationError("Invalid Google ID token") from last_error

    def authenticate(
        self,
        *,
        id_token_raw: str,
        tenant_name: str | None = None,
        full_name: str | None = None,
    ) -> GoogleAuthResult:
        payload = self.verify_id_token(id_token_raw)
        provider_uid = payload.get("sub")
        email = (payload.get("email") or "").strip().lower()
        name = (full_name or payload.get("name") or "").strip()

        if not provider_uid or not email:
            raise ValidationError("Google account must include email")

        social = (
            SocialAccount.objects.select_related("user")
            .filter(provider=SocialAccount.Provider.GOOGLE, provider_uid=provider_uid)
            .first()
        )
        if social:
            return self._build_result(social.user, is_new_user=False)

        user = User.objects.filter(email=email).first()
        if user:
            self._link_google(user, provider_uid, email)
            return self._build_result(user, is_new_user=False)

        if not tenant_name or not tenant_name.strip():
            raise ValidationError(
                "Organization name is required when signing up with Google",
                code="tenant_required",
            )

        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=None,
                full_name=name,
            )
            user.set_unusable_password()
            user.save(update_fields=["password"])

            tenant = self._create_tenant(tenant_name.strip())
            TenantMembership.objects.create(
                tenant=tenant,
                user=user,
                role=TenantMembership.Role.OWNER,
            )
            self._link_google(user, provider_uid, email)

        return self._build_result(user, is_new_user=True)

    def link_google(self, *, user: User, id_token_raw: str) -> None:
        payload = self.verify_id_token(id_token_raw)
        provider_uid = payload.get("sub")
        email = (payload.get("email") or "").strip().lower()

        if not provider_uid or not email:
            raise ValidationError("Google account must include email")
        if email != user.email.lower():
            raise ValidationError("Google email must match your account email")

        existing = SocialAccount.objects.filter(
            provider=SocialAccount.Provider.GOOGLE,
            provider_uid=provider_uid,
        ).exclude(user=user).first()
        if existing:
            raise ConflictError("This Google account is linked to another user")

        if SocialAccount.objects.filter(
            user=user,
            provider=SocialAccount.Provider.GOOGLE,
        ).exists():
            raise ConflictError("Google is already linked to this account")

        self._link_google(user, provider_uid, email)

    def set_password(self, *, user: User, password: str) -> None:
        if user.has_usable_password():
            raise ConflictError("Password is already set. Use change password instead.")
        if len(password) < 10:
            raise ValidationError("Password must be at least 10 characters")
        user.set_password(password)
        user.save(update_fields=["password"])

    def get_auth_methods(self, user: User) -> dict[str, bool]:
        return {
            "has_password": user.has_usable_password(),
            "has_google": SocialAccount.objects.filter(
                user=user,
                provider=SocialAccount.Provider.GOOGLE,
            ).exists(),
        }

    def _link_google(self, user: User, provider_uid: str, email: str) -> SocialAccount:
        account, _ = SocialAccount.objects.get_or_create(
            provider=SocialAccount.Provider.GOOGLE,
            provider_uid=provider_uid,
            defaults={"user": user, "email": email},
        )
        if account.user_id != user.id:
            raise ConflictError("This Google account is linked to another user")
        return account

    def _create_tenant(self, tenant_name: str) -> Tenant:
        base_slug = slugify(tenant_name) or "workspace"
        slug = base_slug
        counter = 1
        while Tenant.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return Tenant.objects.create(
            id=uuid.uuid4(),
            name=tenant_name,
            slug=slug,
        )

    def _build_result(self, user: User, *, is_new_user: bool) -> GoogleAuthResult:
        membership = (
            TenantMembership.objects.select_related("tenant")
            .filter(user=user, tenant__is_active=True)
            .order_by("created_at")
            .first()
        )
        tenant = membership.tenant if membership else None
        role = membership.role if membership else None
        return GoogleAuthResult(
            user=user,
            tenant=tenant,
            role=role,
            is_new_user=is_new_user,
        )
