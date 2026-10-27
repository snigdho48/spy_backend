from rest_framework import serializers


class WorkspaceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)


class SubscribeSerializer(serializers.Serializer):
    plan_code = serializers.CharField(max_length=32)
