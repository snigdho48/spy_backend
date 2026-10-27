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
        return data
