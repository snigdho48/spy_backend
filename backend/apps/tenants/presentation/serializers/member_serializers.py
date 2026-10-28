from rest_framework import serializers

from apps.tenants.infrastructure.models.membership import TenantMembership


class InviteCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(
        choices=[
            TenantMembership.Role.ADMIN,
            TenantMembership.Role.MONITOR,
            TenantMembership.Role.VIEWER,
        ],
        default=TenantMembership.Role.VIEWER,
    )


class ChangeRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(
        choices=[
            TenantMembership.Role.OWNER,
            TenantMembership.Role.ADMIN,
            TenantMembership.Role.MONITOR,
            TenantMembership.Role.VIEWER,
        ]
    )


class InviteTokenSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=16, max_length=128)
