from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.devices.application.services.screen_share_service import ScreenShareService
from apps.devices.infrastructure.models.screen_share import ScreenShareSession
from apps.devices.presentation.serializers.screen_share_serializers import (
    ScreenShareEndSerializer,
    ScreenShareSessionSerializer,
)
from core.domain.exceptions import EntityNotFoundError


class _TenantMixin:
    def get_tenant(self):
        if not hasattr(self, "_cached_tenant"):
            auth = AuthenticationService()
            self._cached_tenant = auth.get_user_tenant(self.request.user)
        if not self._cached_tenant:
            raise EntityNotFoundError("No active tenant membership")
        return self._cached_tenant


class ScreenShareRequestView(_TenantMixin, APIView):
    """Monitor requests a live screen-share session for a tenant device."""

    permission_classes = [IsAuthenticated]

    def post(self, request, device_id):
        session, created = ScreenShareService().request_session(
            user=request.user,
            tenant=self.get_tenant(),
            device_id=device_id,
        )
        return Response(
            ScreenShareSessionSerializer(session).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class OwnedScreenSharePendingView(APIView):
    """Monitored device owner polls for pending/active screen-share requests."""

    permission_classes = [IsAuthenticated]

    def get(self, request, device_id):
        from apps.devices.infrastructure.models.device import Device

        device = Device.objects.filter(owner=request.user, pk=device_id).first()
        if not device:
            raise EntityNotFoundError("Device not found")
        ScreenShareService().expire_stale_requested(device=device)
        sessions = ScreenShareSession.objects.filter(
            device=device,
            status__in=[
                ScreenShareSession.Status.REQUESTED,
                ScreenShareSession.Status.ACTIVE,
            ],
        ).select_related("device", "requested_by")
        return Response(
            {"results": ScreenShareSessionSerializer(sessions, many=True).data}
        )


class ScreenShareStartView(APIView):
    """Monitored device owner accepts a request and begins streaming."""

    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = ScreenShareService().start_session(
            user=request.user, session_id=session_id
        )
        return Response(ScreenShareSessionSerializer(session).data)


class ScreenShareDenyView(APIView):
    """Monitored device owner declines a pending request."""

    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        serializer = ScreenShareEndSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = ScreenShareService().deny_session(
            user=request.user,
            session_id=session_id,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(ScreenShareSessionSerializer(session).data)


class ScreenShareEndView(APIView):
    """Either side ends an open session."""

    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        serializer = ScreenShareEndSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = ScreenShareService().end_session(
            user=request.user,
            session_id=session_id,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(ScreenShareSessionSerializer(session).data)


class ScreenShareStatusView(APIView):
    """Read current session status (monitor or monitored owner)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        session = ScreenShareService().get_session_for_user(
            user=request.user, session_id=session_id
        )
        return Response(ScreenShareSessionSerializer(session).data)
