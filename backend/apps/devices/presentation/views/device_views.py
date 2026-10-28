from django.conf import settings
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.devices.application.services.device_access import DeviceAccessService
from apps.devices.application.services.pairing_service import (
    DeviceManagementService,
    DevicePairingService,
)
from apps.devices.application.services.sharing_pause_service import SharingPauseService
from apps.devices.infrastructure.models.device import Device
from apps.devices.presentation.serializers.device_serializers import (
    DeviceDetailSerializer,
    DevicePhotoSerializer,
    DeviceSerializer,
    PairingCompleteSerializer,
    PairingInitiateSerializer,
    SharingPauseSerializer,
    sharing_payload,
)
from core.domain.exceptions import EntityNotFoundError


class TenantMixin:
    def get_tenant(self):
        if not hasattr(self, "_cached_tenant"):
            auth = AuthenticationService()
            self._cached_tenant = auth.get_user_tenant(self.request.user)
        if not self._cached_tenant:
            raise EntityNotFoundError("No active tenant membership")
        return self._cached_tenant


class DeviceListView(TenantMixin, generics.ListAPIView):
    serializer_class = DeviceSerializer

    def get_queryset(self):
        tenant = self.get_tenant()
        return (
            DeviceAccessService()
            .accessible_devices_qs(user=self.request.user, tenant=tenant)
            .select_related("owner")
            .order_by("-created_at")
        )


class OwnedDeviceListView(APIView):
    """Devices owned by the signed-in user (monitored phone)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        devices = (
            Device.objects.filter(owner=request.user)
            .select_related("owner", "tenant")
            .order_by("-updated_at")
        )
        return Response({"results": DeviceSerializer(devices, many=True).data})


class OwnedDeviceStatusView(APIView):
    """Lightweight pairing status poll for the monitored device."""

    permission_classes = [IsAuthenticated]

    def get(self, request, device_id):
        from apps.tenants.application.services.workspace_service import WorkspaceService

        device = (
            Device.objects.filter(owner=request.user, pk=device_id)
            .select_related("tenant")
            .first()
        )
        if not device:
            raise EntityNotFoundError("Device not found")

        is_linked = (
            device.status == Device.Status.ACTIVE
            and not WorkspaceService.is_staging_tenant(device.tenant)
        )
        return Response(
            {
                "device_id": device.id,
                "device_name": device.name,
                "status": device.status,
                "tenant_name": device.tenant.name,
                "is_linked": is_linked,
                "sharing": sharing_payload(device),
            }
        )


class OwnedDevicePauseView(APIView):
    """Monitored device owner pauses telemetry upload temporarily."""

    permission_classes = [IsAuthenticated]

    def post(self, request, device_id):
        serializer = SharingPauseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pause = SharingPauseService().pause(
            user=request.user,
            device_id=device_id,
            duration_minutes=serializer.validated_data["duration_minutes"],
            reason=serializer.validated_data.get("reason", ""),
        )
        device = pause.device
        return Response(
            {
                "device_id": device.id,
                "sharing": sharing_payload(device),
            },
            status=status.HTTP_200_OK,
        )


class OwnedDeviceResumeView(APIView):
    """Monitored device owner resumes telemetry upload."""

    permission_classes = [IsAuthenticated]

    def post(self, request, device_id):
        device = SharingPauseService().resume(
            user=request.user,
            device_id=device_id,
        )
        return Response(
            {
                "device_id": device.id,
                "sharing": sharing_payload(device),
            },
            status=status.HTTP_200_OK,
        )


class DeviceDetailView(TenantMixin, APIView):
    def get(self, request, device_id):
        tenant = self.get_tenant()
        device = DeviceAccessService().get_accessible_device(
            user=request.user, tenant=tenant, device_id=device_id
        )
        return Response(DeviceDetailSerializer(device).data)

    def patch(self, request, device_id):
        serializer = DevicePhotoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = self.get_tenant()
        device = DeviceManagementService().set_photo_url(
            user=request.user,
            tenant=tenant,
            device_id=device_id,
            photo_url=serializer.validated_data["photo_url"],
        )
        return Response(DeviceSerializer(device).data)

    def delete(self, request, device_id):
        tenant = self.get_tenant()
        DeviceManagementService().delete_device(
            user=request.user,
            tenant=tenant,
            device_id=device_id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceDisconnectView(TenantMixin, APIView):
    """Stop monitoring: revoke consent and mark device as disconnected."""

    def post(self, request, device_id):
        tenant = self.get_tenant()
        device = DeviceManagementService().disconnect_device(
            user=request.user,
            tenant=tenant,
            device_id=device_id,
        )
        return Response(DeviceSerializer(device).data)


class PairingInitiateView(APIView):
    """Monitored device: any signed-in user may generate a pairing code (no workspace/plan)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PairingInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pairing = DevicePairingService().initiate_pairing(
            user=request.user,
            **serializer.validated_data,
        )
        return Response(
            {
                "pairing_id": pairing.id,
                "device_id": pairing.device_id,
                "pairing_code": pairing.pairing_code,
                "qr_payload": (
                    f"spylove://pair?code={pairing.pairing_code}"
                    f"&token={pairing.pairing_token}"
                ),
                "expires_at": pairing.expires_at,
            },
            status=status.HTTP_201_CREATED,
        )


class PairingCompleteView(TenantMixin, APIView):
    """Monitor account: approves pairing and attaches device to their workspace."""
    def post(self, request):
        serializer = PairingCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not data.get("consent_version"):
            data["consent_version"] = settings.CONSENT_VERSION

        device, consent = DevicePairingService().complete_pairing(
            user=request.user,
            tenant=self.get_tenant(),
            **data,
        )
        return Response(
            {
                "device": DeviceSerializer(device).data,
                "consent": {
                    "id": consent.id,
                    "scopes": consent.scopes,
                    "consent_version": consent.consent_version,
                    "granted_at": consent.granted_at,
                    "revoked_at": consent.revoked_at,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class ConsentRevokeView(TenantMixin, APIView):
    def delete(self, request, device_id):
        tenant = self.get_tenant()
        DeviceManagementService().disconnect_device(
            user=request.user,
            tenant=tenant,
            device_id=device_id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
