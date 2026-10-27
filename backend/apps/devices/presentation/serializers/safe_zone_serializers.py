from rest_framework import serializers

from apps.devices.infrastructure.models.device import SafeZone


class SafeZoneSerializer(serializers.ModelSerializer):
    device_id = serializers.UUIDField(source="device.id", allow_null=True, read_only=True)
    created_by_email = serializers.EmailField(
        source="created_by.email", read_only=True, allow_null=True
    )
    display_label = serializers.CharField(read_only=True)

    class Meta:
        model = SafeZone
        fields = [
            "id",
            "name",
            "address",
            "lat",
            "lng",
            "radius_m",
            "device_id",
            "created_by_email",
            "display_label",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SafeZoneWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    address = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    radius_m = serializers.IntegerField(required=False, default=100)
    device_id = serializers.UUIDField(required=False, allow_null=True)


class SafeZonePatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, required=False)
    address = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    lat = serializers.FloatField(required=False)
    lng = serializers.FloatField(required=False)
    radius_m = serializers.IntegerField(required=False)
    device_id = serializers.UUIDField(required=False, allow_null=True)
