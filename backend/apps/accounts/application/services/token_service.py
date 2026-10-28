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
    request=None,
    device_label: str = "",
) -> dict:
    auth_service = AuthenticationService()
    google_service = GoogleAuthService()
    membership = auth_service.get_user_membership(user)

    refresh = RefreshToken.for_user(user)
    refresh["email"] = user.email
    if membership:
        refresh["tenant_id"] = str(membership.tenant_id)
        refresh["role"] = membership.role

    if request is not None:
        from apps.accounts.application.services.session_service import SessionService

        label = device_label
        if not label and hasattr(request, "data"):
            label = request.data.get("device_label", "") or ""
        SessionService().record_login(
            user=user,
            refresh=refresh,
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            device_label=label,
        )

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


def _client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None
