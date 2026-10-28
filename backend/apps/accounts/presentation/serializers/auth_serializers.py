from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.tenants.application.services.workspace_service import WorkspaceService


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=10)
    full_name = serializers.CharField(max_length=255)
    tenant_name = serializers.CharField(max_length=255)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.CharField()


class TenantSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class AuthResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    tenant = TenantSerializer(required=False)
    tokens = TokenPairSerializer()


class GoogleLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField()
    full_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    tenant_name = serializers.CharField(max_length=255, required=False, allow_blank=True)


class LinkGoogleSerializer(serializers.Serializer):
    id_token = serializers.CharField()


class SetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, min_length=10)


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        membership = (
            user.tenant_memberships.select_related("tenant")
            .filter(tenant__is_active=True)
            .order_by("created_at")
            .first()
        )
        if membership:
            token["tenant_id"] = str(membership.tenant_id)
            token["role"] = membership.role
        return token

    def validate(self, attrs):
        # Authenticate first so we can branch before issuing JWTs when 2FA is on.
        authenticate_kwargs = {
            self.username_field: attrs[self.username_field],
            "password": attrs["password"],
        }
        self.user = self.context["request"].user  # placeholder cleared below
        from django.contrib.auth import authenticate as dj_authenticate

        request = self.context.get("request")
        self.user = dj_authenticate(request=request, **authenticate_kwargs)
        if self.user is None or not self.user.is_active:
            from rest_framework_simplejwt.exceptions import AuthenticationFailed
            from django.utils.translation import gettext_lazy as _

            raise AuthenticationFailed(
                _("No active account found with the given credentials"),
                "no_active_account",
            )

        if getattr(self.user, "totp_enabled", False):
            from apps.accounts.application.services.totp_service import TotpService

            return {
                "requires_2fa": True,
                "pre_auth_token": TotpService().issue_pre_auth_token(self.user),
                "user": {
                    "id": self.user.id,
                    "email": self.user.email,
                    "full_name": self.user.full_name,
                },
            }

        data = super().validate(attrs)
        data["user"] = {
            "id": self.user.id,
            "email": self.user.email,
            "full_name": self.user.full_name,
        }
        membership = (
            self.user.tenant_memberships.select_related("tenant")
            .filter(tenant__is_active=True)
            .exclude(tenant__slug__startswith=WorkspaceService.STAGING_SLUG_PREFIX)
            .order_by("created_at")
            .first()
        )
        data["needs_workspace"] = membership is None
        if membership:
            tenant = membership.tenant
            data["tenant"] = {
                "id": membership.tenant_id,
                "name": tenant.name,
                "slug": tenant.slug,
                "plan": tenant.plan,
            }
            data["role"] = membership.role
            from apps.tenants.application.services.workspace_service import SubscriptionService

            data["subscription"] = SubscriptionService().get_tenant_subscription(tenant)
        from apps.accounts.application.services.google_auth_service import GoogleAuthService

        data["auth_methods"] = GoogleAuthService().get_auth_methods(self.user)
        data["requires_2fa"] = False
        return data


class TotpCodeSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=6, max_length=16)


class TotpDisableSerializer(serializers.Serializer):
    password = serializers.CharField(required=False, allow_blank=True)
    code = serializers.CharField(required=False, allow_blank=True, max_length=16)


class TotpVerifyLoginSerializer(serializers.Serializer):
    pre_auth_token = serializers.CharField()
    code = serializers.CharField(min_length=6, max_length=16)
