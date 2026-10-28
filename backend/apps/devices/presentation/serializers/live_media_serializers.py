from rest_framework import serializers

from apps.devices.infrastructure.models.live_media import LiveMediaSession


class LiveMediaSessionSerializer(serializers.ModelSerializer):
    device_id = serializers.UUIDField(source="device.id", read_only=True)
    device_name = serializers.CharField(source="device.name", read_only=True)
    requested_by_email = serializers.EmailField(
        source="requested_by.email", read_only=True
    )
    ws_url = serializers.SerializerMethodField()

    class Meta:
        model = LiveMediaSession
        fields = [
            "id",
            "device_id",
            "device_name",
            "requested_by_email",
            "media_kind",
            "camera_facing",
            "status",
            "requested_at",
            "started_at",
            "ended_at",
            "ended_reason",
            "created_at",
            "ws_url",
        ]
        read_only_fields = fields

    def get_ws_url(self, obj: LiveMediaSession) -> str:
        return f"ws/v1/media/{obj.id}/"


class LiveMediaRequestSerializer(serializers.Serializer):
    media_kind = serializers.ChoiceField(
        choices=LiveMediaSession.MediaKind.values,
        default=LiveMediaSession.MediaKind.CAMERA,
    )
    camera_facing = serializers.ChoiceField(
        choices=["front", "back"], default="back", required=False
    )


class LiveMediaFacingSerializer(serializers.Serializer):
    facing = serializers.ChoiceField(choices=["front", "back"])


class LiveMediaEndSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=False, allow_blank=True, max_length=255, default=""
    )
