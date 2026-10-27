from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.devices.application.services.safe_zone_service import SafeZoneService
from apps.devices.presentation.serializers.safe_zone_serializers import (
    SafeZonePatchSerializer,
    SafeZoneSerializer,
    SafeZoneWriteSerializer,
)


class SafeZoneListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        zones = SafeZoneService().list_for_user(request.user)
        return Response({"results": SafeZoneSerializer(zones, many=True).data})

    def post(self, request):
        serializer = SafeZoneWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        zone = SafeZoneService().create(
            user=request.user,
            name=data["name"],
            lat=data["lat"],
            lng=data["lng"],
            radius_m=data.get("radius_m", 100),
            address=data.get("address", ""),
            device_id=data.get("device_id"),
        )
        return Response(
            SafeZoneSerializer(zone).data, status=status.HTTP_201_CREATED
        )


class SafeZoneDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, zone_id):
        serializer = SafeZonePatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        zone = SafeZoneService().update(
            user=request.user,
            zone_id=zone_id,
            **serializer.validated_data,
        )
        return Response(SafeZoneSerializer(zone).data)

    def delete(self, request, zone_id):
        SafeZoneService().delete(user=request.user, zone_id=zone_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
