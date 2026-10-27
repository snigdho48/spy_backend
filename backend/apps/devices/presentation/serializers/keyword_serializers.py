from rest_framework import serializers

from apps.devices.infrastructure.models.device import WatchlistKeyword


class WatchlistKeywordSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(
        source="created_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = WatchlistKeyword
        fields = ["id", "word", "created_by_email", "created_at"]
        read_only_fields = fields


class WatchlistKeywordWriteSerializer(serializers.Serializer):
    word = serializers.CharField(max_length=64)
