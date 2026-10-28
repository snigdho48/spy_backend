from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.alerts.application.services.alert_service import (
    AlertService,
    PushTokenService,
)
from apps.alerts.presentation.serializers.alert_serializers import (
    AlertSerializer,
    PushTokenSerializer,
    PushTokenWriteSerializer,
)
from core.domain.exceptions import EntityNotFoundError, ValidationError
from core.presentation.pagination import StandardPagination


class TenantMixin:
    def get_tenant(self):
        if not hasattr(self, "_cached_tenant"):
            self._cached_tenant = AuthenticationService().get_user_tenant(
                self.request.user
            )
        if not self._cached_tenant:
            raise EntityNotFoundError("No active tenant membership")
        return self._cached_tenant


class AlertListView(TenantMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = self.get_tenant()
        unread = request.query_params.get("unread", "").lower() in (
            "1",
            "true",
            "yes",
        )
        qs = AlertService().list_for_user(
            user=request.user,
            tenant=tenant,
            device_id=request.query_params.get("device_id"),
            alert_type=request.query_params.get("type"),
            unread_only=unread,
        )
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            AlertSerializer(page, many=True).data
        )


class AlertMarkReadView(TenantMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, alert_id):
        alert = AlertService().mark_read(
            user=request.user, tenant=self.get_tenant(), alert_id=alert_id
        )
        return Response(AlertSerializer(alert).data)


class AlertMarkAllReadView(TenantMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        count = AlertService().mark_all_read(
            user=request.user,
            tenant=self.get_tenant(),
            device_id=request.query_params.get("device_id")
            or request.data.get("device_id"),
        )
        return Response({"marked": count})


class AlertDeleteView(TenantMixin, APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, alert_id):
        AlertService().delete_alert(
            user=request.user, tenant=self.get_tenant(), alert_id=alert_id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PushTokenRegisterView(TenantMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PushTokenWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        token = PushTokenService().register(
            user=request.user,
            tenant=self.get_tenant(),
            token=data["token"],
            platform=data.get("platform", "android"),
        )
        return Response(
            PushTokenSerializer(token).data, status=status.HTTP_201_CREATED
        )


class PushTokenUnregisterView(TenantMixin, APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, token_id=None):
        raw_token = request.data.get("token") if hasattr(request, "data") else None
        if token_id is None and not raw_token:
            raw_token = request.query_params.get("token")
        if token_id is None and not raw_token:
            raise ValidationError("token or token_id is required")
        deleted = PushTokenService().unregister(
            user=request.user,
            tenant=self.get_tenant(),
            token=raw_token,
            token_id=token_id,
        )
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)
