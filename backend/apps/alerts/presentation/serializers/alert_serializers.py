from rest_framework import serializers

from apps.alerts.infrastructure.models.alert import Alert, PushToken


class AlertSerializer(serializers.ModelSerializer):
    device_id = serializers.UUIDField(source="device.id", read_only=True)
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Alert
        fields = [
            "id",
            "device_id",
            "type",
            "severity",
            "title",
            "body",
            "metadata",
            "created_at",
            "read_at",
            "is_read",
        ]
        read_only_fields = fields


class PushTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = PushToken
        fields = ["id", "token", "platform", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class PushTokenWriteSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=512)
    platform = serializers.ChoiceField(
        choices=PushToken.Platform.choices, default=PushToken.Platform.ANDROID
    )
