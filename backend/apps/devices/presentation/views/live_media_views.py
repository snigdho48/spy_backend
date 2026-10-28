from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.devices.application.services.live_media_service import LiveMediaService
from apps.devices.infrastructure.models.live_media import LiveMediaSession
from apps.devices.presentation.serializers.live_media_serializers import (
    LiveMediaEndSerializer,
    LiveMediaFacingSerializer,
    LiveMediaRequestSerializer,
    LiveMediaSessionSerializer,
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


class LiveMediaRequestView(_TenantMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, device_id):
        ser = LiveMediaRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        session, created = LiveMediaService().request_session(
            user=request.user,
            tenant=self.get_tenant(),
            device_id=device_id,
            media_kind=ser.validated_data["media_kind"],
            camera_facing=ser.validated_data.get("camera_facing", "back"),
        )
        return Response(
            LiveMediaSessionSerializer(session).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class OwnedLiveMediaPendingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, device_id):
        from apps.devices.infrastructure.models.device import Device

        device = Device.objects.filter(owner=request.user, pk=device_id).first()
        if not device:
            raise EntityNotFoundError("Device not found")
        LiveMediaService().expire_stale_requested(device=device)
        sessions = LiveMediaSession.objects.filter(
            device=device,
            status__in=[
                LiveMediaSession.Status.REQUESTED,
                LiveMediaSession.Status.ACTIVE,
            ],
        ).select_related("device", "requested_by")
        return Response(
            {"results": LiveMediaSessionSerializer(sessions, many=True).data}
        )


class LiveMediaStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = LiveMediaService().start_session(
            user=request.user, session_id=session_id
        )
        return Response(LiveMediaSessionSerializer(session).data)


class LiveMediaFacingView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        ser = LiveMediaFacingSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        session = LiveMediaService().update_facing(
            user=request.user,
            session_id=session_id,
            facing=ser.validated_data["facing"],
        )
        return Response(LiveMediaSessionSerializer(session).data)


class LiveMediaEndView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        ser = LiveMediaEndSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        session = LiveMediaService().end_session(
            user=request.user,
            session_id=session_id,
            reason=ser.validated_data.get("reason", ""),
        )
        return Response(LiveMediaSessionSerializer(session).data)


class LiveMediaStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        session = LiveMediaService().get_session_for_user(
            user=request.user, session_id=session_id
        )
        return Response(LiveMediaSessionSerializer(session).data)
