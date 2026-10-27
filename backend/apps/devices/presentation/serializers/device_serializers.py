from rest_framework import serializers

from apps.devices.infrastructure.models.device import Device


def sharing_payload(device: Device) -> dict:
    from apps.devices.application.services.sharing_pause_service import (
        SharingPauseService,
    )

    return SharingPauseService().sharing_state(device)


class DeviceSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    owner_name = serializers.CharField(source="owner.full_name", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    sharing = serializers.SerializerMethodField()

    class Meta:
        model = Device
        fields = [
            "id",
            "name",
            "platform",
            "status",
            "last_seen_at",
            "photo_url",
            "created_at",
            "updated_at",
            "owner_email",
            "owner_name",
            "tenant_name",
            "sharing",
        ]
        read_only_fields = fields

    def get_sharing(self, obj: Device) -> dict:
        return sharing_payload(obj)


class DevicePhotoSerializer(serializers.Serializer):
    photo_url = serializers.CharField(
        max_length=2048, allow_blank=True, required=True
    )


class DeviceDetailSerializer(DeviceSerializer):
    consent = serializers.SerializerMethodField()

    class Meta(DeviceSerializer.Meta):
        fields = DeviceSerializer.Meta.fields + ["consent"]

    def get_consent(self, obj: Device) -> dict | None:
        from apps.devices.application.services.pairing_service import ConsentService

        consent = ConsentService().get_active_consent(obj)
        if not consent:
            return None
        return {
            "id": consent.id,
            "scopes": consent.scopes,
            "consent_version": consent.consent_version,
            "granted_at": consent.granted_at,
            "revoked_at": consent.revoked_at,
        }


class SharingPauseSerializer(serializers.Serializer):
    duration_minutes = serializers.IntegerField()
    reason = serializers.CharField(
        required=False, allow_blank=True, max_length=255, default=""
    )


class PairingInitiateSerializer(serializers.Serializer):
    device_name = serializers.CharField(max_length=255)
    platform = serializers.ChoiceField(choices=Device.Platform.choices)
    device_fingerprint = serializers.CharField(max_length=255)


class PairingCompleteSerializer(serializers.Serializer):
    pairing_code = serializers.CharField(max_length=16)
    consent_scopes = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
    )
    consent_version = serializers.CharField(max_length=32)


class ConsentRecordSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    scopes = serializers.ListField(child=serializers.CharField())
    consent_version = serializers.CharField()
    granted_at = serializers.DateTimeField()
    revoked_at = serializers.DateTimeField(allow_null=True)
