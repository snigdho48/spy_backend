from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.events.application.services.ingestion_service import EventIngestionService
from apps.events.infrastructure.models.event import DeviceEvent
from apps.events.infrastructure.models.snapshots import (
    DeviceAppInventorySnapshot,
    DeviceContactSnapshot,
)
from apps.events.presentation.serializers.event_serializers import (
    DeviceAppInventorySnapshotSerializer,
    DeviceContactSnapshotSerializer,
    DeviceEventSerializer,
    EventBatchSerializer,
)
from core.domain.exceptions import EntityNotFoundError, ValidationError


class EventRateThrottle(UserRateThrottle):
    scope = "events"


class TenantMixin:
    def get_tenant(self):
        if not hasattr(self, "_cached_tenant"):
            auth = AuthenticationService()
            self._cached_tenant = auth.get_user_tenant(self.request.user)
        if not self._cached_tenant:
            raise EntityNotFoundError("No active tenant membership")
        return self._cached_tenant


class EventIngestView(APIView):
    """Monitored device uploads events (device owner, any workspace)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [EventRateThrottle]

    def post(self, request):
        serializer = EventBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = EventIngestionService().ingest_batch(
            user=request.user,
            device_id=data["device_id"],
            events=data["events"],
        )
        return Response(result, status=status.HTTP_202_ACCEPTED)


class EventListView(TenantMixin, generics.ListAPIView):
    serializer_class = DeviceEventSerializer
    filterset_fields = ["device_id", "event_type"]

    def get_queryset(self):
        tenant = self.get_tenant()
        qs = DeviceEvent.objects.filter(tenant=tenant).select_related("device")
        device_id = self.request.query_params.get("device_id")
        if device_id:
            qs = qs.filter(device_id=device_id)
        event_type = self.request.query_params.get("event_type")
        if event_type:
            qs = qs.filter(event_type=event_type)
        event_prefix = self.request.query_params.get("event_prefix")
        if event_prefix:
            qs = qs.filter(event_type__startswith=f"{event_prefix}.")
        return qs.order_by("-event_timestamp", "-created_at")


class ContactSnapshotLatestView(TenantMixin, APIView):
    """Latest address-book snapshot for a device in the monitor's tenant."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = self.get_tenant()
        device_id = request.query_params.get("device_id")
        if not device_id:
            raise ValidationError("device_id is required")
        snap = (
            DeviceContactSnapshot.objects.filter(tenant=tenant, device_id=device_id)
            .select_related("device")
            .first()
        )
        if not snap:
            raise EntityNotFoundError("No contact snapshot for this device")
        return Response(DeviceContactSnapshotSerializer(snap).data)


class AppInventorySnapshotLatestView(TenantMixin, APIView):
    """Latest installed-app inventory for a device in the monitor's tenant."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = self.get_tenant()
        device_id = request.query_params.get("device_id")
        if not device_id:
            raise ValidationError("device_id is required")
        snap = (
            DeviceAppInventorySnapshot.objects.filter(
                tenant=tenant, device_id=device_id
            )
            .select_related("device")
            .first()
        )
        if not snap:
            raise EntityNotFoundError("No app inventory snapshot for this device")
        return Response(DeviceAppInventorySnapshotSerializer(snap).data)
