from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.accounts.application.services.google_auth_service import GoogleAuthService
from apps.accounts.infrastructure.models.user import User
from apps.tenants.application.services.workspace_service import SubscriptionService


def build_auth_payload(
    user: User,
    *,
    is_new_user: bool | None = None,
    include_auth_methods: bool = True,
) -> dict:
    auth_service = AuthenticationService()
    google_service = GoogleAuthService()
    membership = auth_service.get_user_membership(user)

    refresh = RefreshToken.for_user(user)
    refresh["email"] = user.email
    if membership:
        refresh["tenant_id"] = str(membership.tenant_id)
        refresh["role"] = membership.role

    payload: dict = {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
        },
        "tokens": {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        },
        "needs_workspace": membership is None,
    }

    if membership:
        tenant = membership.tenant
        payload["tenant"] = {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "plan": tenant.plan,
        }
        payload["role"] = membership.role
        payload["subscription"] = SubscriptionService().get_tenant_subscription(tenant)

    if include_auth_methods:
        payload["auth_methods"] = google_service.get_auth_methods(user)

    if is_new_user is not None:
        payload["is_new_user"] = is_new_user

    return payload
