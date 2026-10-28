from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.devices.application.services.device_access import DeviceAccessService
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
        access = DeviceAccessService()
        allowed_ids = access.accessible_device_ids(
            user=self.request.user, tenant=tenant
        )
        qs = DeviceEvent.objects.filter(
            tenant=tenant, device_id__in=allowed_ids
        ).select_related("device")

        device_id = self.request.query_params.get("device_id")
        if device_id:
            # Explicit check so unauthorized members get 403, not an empty list.
            access.get_accessible_device(
                user=self.request.user, tenant=tenant, device_id=device_id
            )
            qs = qs.filter(device_id=device_id)

        event_type = self.request.query_params.get("event_type")
        if event_type:
            qs = qs.filter(event_type=event_type)
        event_prefix = self.request.query_params.get("event_prefix")
        if event_prefix:
            qs = qs.filter(event_type__startswith=f"{event_prefix}.")
        return qs.order_by("-event_timestamp", "-created_at")


class ContactSnapshotLatestView(TenantMixin, APIView):
    """Latest address-book snapshot for a device the caller may access."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = self.get_tenant()
        device_id = request.query_params.get("device_id")
        if not device_id:
            raise ValidationError("device_id is required")
        DeviceAccessService().get_accessible_device(
            user=request.user, tenant=tenant, device_id=device_id
        )
        snap = (
            DeviceContactSnapshot.objects.filter(tenant=tenant, device_id=device_id)
            .select_related("device")
            .first()
        )
        if not snap:
            raise EntityNotFoundError("No contact snapshot for this device")
        return Response(DeviceContactSnapshotSerializer(snap).data)


class AppInventorySnapshotLatestView(TenantMixin, APIView):
    """Latest installed-app inventory for a device the caller may access."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = self.get_tenant()
        device_id = request.query_params.get("device_id")
        if not device_id:
            raise ValidationError("device_id is required")
        DeviceAccessService().get_accessible_device(
            user=request.user, tenant=tenant, device_id=device_id
        )
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


class _DeviceFeedView(TenantMixin, APIView):
    """Shared helper: resolve a device the caller may access via ?device_id=."""

    permission_classes = [IsAuthenticated]

    def _resolve_device(self, request):
        tenant = self.get_tenant()
        device_id = request.query_params.get("device_id")
        if not device_id:
            raise ValidationError("device_id is required")
        device = DeviceAccessService().get_accessible_device(
            user=request.user, tenant=tenant, device_id=device_id
        )
        return tenant, device


class AppUsageLatestView(_DeviceFeedView):
    """Latest app-usage / screen-time snapshot for a device."""

    def get(self, request):
        from apps.events.infrastructure.models.snapshots import (
            DeviceAppUsageSnapshot,
        )
        from apps.events.presentation.serializers.event_serializers import (
            DeviceAppUsageSnapshotSerializer,
        )

        tenant, device = self._resolve_device(request)
        snap = DeviceAppUsageSnapshot.objects.filter(
            tenant=tenant, device=device
        ).first()
        if not snap:
            raise EntityNotFoundError("No app-usage snapshot for this device")
        return Response(DeviceAppUsageSnapshotSerializer(snap).data)


class AppUsageRangeView(_DeviceFeedView):
    """Aggregated per-app totals over a date range from app_usage.snapshot events."""

    def get(self, request):
        from django.utils.dateparse import parse_datetime

        tenant, device = self._resolve_device(request)
        qs = DeviceEvent.objects.filter(
            tenant=tenant, device=device, event_type="app_usage.snapshot"
        )
        frm = request.query_params.get("from")
        to = request.query_params.get("to")
        if frm:
            dt = parse_datetime(frm)
            if dt:
                qs = qs.filter(event_timestamp__gte=dt)
        if to:
            dt = parse_datetime(to)
            if dt:
                qs = qs.filter(event_timestamp__lte=dt)

        totals: dict[str, dict] = {}
        for event in qs.only("payload").iterator(chunk_size=200):
            for app in (event.payload or {}).get("apps") or []:
                if not isinstance(app, dict):
                    continue
                pkg = str(app.get("package") or app.get("app_name") or "").strip()
                if not pkg:
                    continue
                row = totals.setdefault(
                    pkg,
                    {
                        "package": pkg,
                        "app_name": app.get("app_name") or pkg,
                        "foreground_ms": 0,
                        "launches": 0,
                    },
                )
                try:
                    row["foreground_ms"] += int(app.get("foreground_ms") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    row["launches"] += int(app.get("launches") or 0)
                except (TypeError, ValueError):
                    pass

        results = sorted(
            totals.values(), key=lambda r: r["foreground_ms"], reverse=True
        )
        return Response(
            {
                "device_id": str(device.id),
                "from": frm,
                "to": to,
                "app_count": len(results),
                "results": results,
            }
        )


class TelemetryLatestView(_DeviceFeedView):
    """Latest device telemetry snapshot."""

    def get(self, request):
        from apps.events.infrastructure.models.snapshots import (
            DeviceTelemetrySnapshot,
        )
        from apps.events.presentation.serializers.event_serializers import (
            DeviceTelemetrySnapshotSerializer,
        )

        tenant, device = self._resolve_device(request)
        snap = DeviceTelemetrySnapshot.objects.filter(
            tenant=tenant, device=device
        ).first()
        if not snap:
            raise EntityNotFoundError("No telemetry snapshot for this device")
        return Response(DeviceTelemetrySnapshotSerializer(snap).data)


class TelemetryHistoryView(_DeviceFeedView):
    """Short history of device.telemetry events (most recent first)."""

    def get(self, request):
        tenant, device = self._resolve_device(request)
        try:
            limit = int(request.query_params.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 200))
        events = DeviceEvent.objects.filter(
            tenant=tenant, device=device, event_type="device.telemetry"
        ).order_by("-event_timestamp")[:limit]
        results = [
            {
                "payload": event.payload or {},
                "timestamp": event.event_timestamp.isoformat(),
            }
            for event in events
        ]
        return Response({"device_id": str(device.id), "results": results})


class DeviceExportView(TenantMixin, APIView):
    """Export a device's feeds as CSV (streamed) or PDF.

    Query params:
      device_id (required), from, to (ISO-8601),
      feeds=events,locations,app_usage,alerts,telemetry
      export_format=csv|pdf (default csv; alias: fmt)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import HttpResponse, StreamingHttpResponse

        from apps.events.application.services.export_service import (
            DeviceExportService,
        )

        tenant = self.get_tenant()
        device_id = request.query_params.get("device_id")
        if not device_id:
            raise ValidationError("device_id is required")
        svc = DeviceExportService()
        device = svc.resolve_device(
            user=request.user, tenant=tenant, device_id=device_id
        )
        start, end = svc.parse_range(
            request.query_params.get("from"), request.query_params.get("to")
        )
        feeds = svc.parse_feeds(request.query_params.get("feeds"))
        # Use export_format — DRF reserves ?format= for content negotiation.
        fmt = (
            request.query_params.get("export_format")
            or request.query_params.get("fmt")
            or "csv"
        ).lower()
        stamp = timezone.now().strftime("%Y%m%d")
        filename = f"device-{device.id}-{stamp}.{fmt}"

        if fmt == "csv":
            response = StreamingHttpResponse(
                svc.stream_csv(
                    device=device, feeds=feeds, start=start, end=end
                ),
                content_type="text/csv; charset=utf-8",
            )
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        if fmt == "pdf":
            pdf_bytes = svc.build_pdf_bytes(
                device=device, feeds=feeds, start=start, end=end
            )
            response = HttpResponse(pdf_bytes, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        raise ValidationError("export_format must be csv or pdf")


class ActivityFeedView(TenantMixin, APIView):
    """Merged, reverse-chronological activity feed for a single device.

    Query params:
      device_id (required),
      from, to (ISO-8601) — optional window,
      types=location,app_inventory,notifications,app_usage,telemetry,contacts,
            calls,sms,messages,alerts (default: all),
      cursor (opaque, from a previous page's `next`),
      limit (1-100, default 50).

    Authorization matches the other device feeds via DeviceAccessService:
    owner or OWNER/ADMIN/MONITOR workspace member. VIEWER-only membership is
    rejected with 403 (consent scopes are enforced at ingestion time).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.events.application.services.activity_service import (
            ActivityFeedService,
        )

        tenant = self.get_tenant()
        device_id = request.query_params.get("device_id")
        if not device_id:
            raise ValidationError("device_id is required")
        device = DeviceAccessService().get_accessible_device(
            user=request.user, tenant=tenant, device_id=device_id
        )
        svc = ActivityFeedService()
        categories = svc.parse_categories(request.query_params.get("types"))
        start, end = svc.parse_range(
            request.query_params.get("from"), request.query_params.get("to")
        )
        offset = svc.decode_cursor(request.query_params.get("cursor"))
        limit = svc.parse_limit(request.query_params.get("limit"))
        page = svc.build_page(
            device=device,
            categories=categories,
            start=start,
            end=end,
            offset=offset,
            limit=limit,
        )
        return Response(page)
