from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.accounts.application.services.totp_service import TotpService
from apps.accounts.presentation.serializers.auth_serializers import (
    TotpCodeSerializer,
    TotpDisableSerializer,
    TotpVerifyLoginSerializer,
)
from apps.accounts.presentation.views.auth_views import AuthRateThrottle


class TotpStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(TotpService().status(request.user))


class TotpEnrollView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payload = TotpService().enroll(request.user)
        return Response(payload, status=status.HTTP_201_CREATED)


class TotpConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TotpCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = TotpService().verify_and_enable(
            request.user, serializer.validated_data["code"]
        )
        return Response(payload)


class TotpDisableView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TotpDisableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        TotpService().disable(
            request.user,
            password=serializer.validated_data.get("password") or None,
            code=serializer.validated_data.get("code") or None,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class TotpRecoveryCodesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TotpDisableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        codes = TotpService().regenerate_recovery_codes(
            request.user,
            password=serializer.validated_data.get("password") or None,
            code=serializer.validated_data.get("code") or None,
        )
        return Response({"recovery_codes": codes})


class TotpVerifyLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    def post(self, request):
        serializer = TotpVerifyLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = TotpService().complete_login(
            pre_auth_token=serializer.validated_data["pre_auth_token"],
            code=serializer.validated_data["code"],
        )
        return Response(payload)
