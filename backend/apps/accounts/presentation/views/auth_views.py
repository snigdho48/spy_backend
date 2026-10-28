from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.accounts.application.services.auth_service import (
    AuthenticationService,
    RegistrationService,
)
from apps.accounts.application.services.google_auth_service import GoogleAuthService
from apps.accounts.application.services.token_service import build_auth_payload
from apps.accounts.presentation.serializers.auth_serializers import (
    CustomTokenObtainPairSerializer,
    GoogleLoginSerializer,
    LinkGoogleSerializer,
    RegisterSerializer,
    SetPasswordSerializer,
)


class AuthRateThrottle(AnonRateThrottle):
    scope = "auth"


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = RegistrationService().register(**serializer.validated_data)

        return Response(
            build_auth_payload(result.user, is_new_user=True),
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]
    serializer_class = CustomTokenObtainPairSerializer


class LogoutView(APIView):
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        user = request.user
        auth_service = AuthenticationService()
        google_service = GoogleAuthService()
        membership = auth_service.get_user_membership(user)
        payload = {
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
            },
            "auth_methods": google_service.get_auth_methods(user),
            "needs_workspace": membership is None,
            "totp_enabled": bool(user.totp_enabled),
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
            from apps.tenants.application.services.workspace_service import SubscriptionService

            payload["subscription"] = SubscriptionService().get_tenant_subscription(tenant)
        return Response(payload)


class GoogleLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        serializer = GoogleLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = GoogleAuthService().authenticate(
            id_token_raw=data["id_token"],
            tenant_name=data.get("tenant_name"),
            full_name=data.get("full_name"),
        )
        return Response(
            build_auth_payload(result.user, is_new_user=result.is_new_user),
            status=status.HTTP_201_CREATED if result.is_new_user else status.HTTP_200_OK,
        )


class LinkGoogleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LinkGoogleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        GoogleAuthService().link_google(
            user=request.user,
            id_token_raw=serializer.validated_data["id_token"],
        )
        return Response({"auth_methods": GoogleAuthService().get_auth_methods(request.user)})


class SetPasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        GoogleAuthService().set_password(
            user=request.user,
            password=serializer.validated_data["password"],
        )
        return Response({"auth_methods": GoogleAuthService().get_auth_methods(request.user)})



class AccountDeleteView(APIView):
    """GDPR right-to-erasure: permanently delete the authenticated account."""

    permission_classes = [IsAuthenticated]

    def delete(self, request):
        from apps.accounts.application.services.gdpr_service import GdprService

        result = GdprService().delete_account(request.user)
        return Response(result, status=status.HTTP_200_OK)


class AccountExportView(APIView):
    """GDPR right-to-access / portability: stream owned devices + events as JSON."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import StreamingHttpResponse
        from apps.accounts.application.services.gdpr_service import GdprService

        chunks = GdprService().iter_export_chunks(request.user)
        response = StreamingHttpResponse(chunks, content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="my-data-export.json"'
        return response
