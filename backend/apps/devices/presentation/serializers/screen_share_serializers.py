from rest_framework import serializers

from apps.devices.infrastructure.models.screen_share import ScreenShareSession


class ScreenShareSessionSerializer(serializers.ModelSerializer):
    device_id = serializers.UUIDField(source="device.id", read_only=True)
    device_name = serializers.CharField(source="device.name", read_only=True)
    requested_by_email = serializers.EmailField(
        source="requested_by.email", read_only=True
    )
    ws_url = serializers.SerializerMethodField()

    class Meta:
        model = ScreenShareSession
        fields = [
            "id",
            "device_id",
            "device_name",
            "requested_by_email",
            "status",
            "requested_at",
            "started_at",
            "ended_at",
            "ended_reason",
            "created_at",
            "ws_url",
        ]
        read_only_fields = fields

    def get_ws_url(self, obj: ScreenShareSession) -> str:
        # Relative path; the client joins it to its WS base + ?token=<jwt>.
        return f"ws/v1/screen/{obj.id}/"


class ScreenShareEndSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=False, allow_blank=True, max_length=255, default=""
    )
