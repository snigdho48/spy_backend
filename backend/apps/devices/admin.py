"""Django admin for devices, consent, pairing, and screen share.

Pairing codes and pairing tokens are omitted from changelist columns.
"""

from django.contrib import admin

from apps.devices.models import (
    ConsentRecord,
    Device,
    DevicePairing,
    SafeZone,
    ScreenShareSession,
    SharingPause,
    WatchlistKeyword,
)

_IDENTITY_FIELDS = ("id", "created_at", "updated_at")


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "platform",
        "status",
        "owner",
        "tenant",
        "last_seen_at",
        "created_at",
    )
    list_filter = ("platform", "status", "tenant")
    search_fields = ("name", "device_fingerprint", "owner__email", "owner__full_name")
    list_select_related = ("owner", "tenant")
    autocomplete_fields = ("owner", "tenant")
    ordering = ("-created_at",)
    readonly_fields = (*_IDENTITY_FIELDS, "last_seen_at")
    date_hierarchy = "created_at"

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            readonly.append("device_fingerprint")
        return readonly


@admin.register(SharingPause)
class SharingPauseAdmin(admin.ModelAdmin):
    list_display = (
        "device",
        "tenant",
        "started_at",
        "expires_at",
        "ended_at",
        "created_by",
    )
    list_filter = (("ended_at", admin.EmptyFieldListFilter), "tenant")
    search_fields = ("device__name", "created_by__email", "reason")
    list_select_related = ("device", "tenant", "created_by")
    autocomplete_fields = ("device", "tenant", "created_by")
    ordering = ("-started_at",)
    readonly_fields = _IDENTITY_FIELDS


@admin.register(WatchlistKeyword)
class WatchlistKeywordAdmin(admin.ModelAdmin):
    list_display = ("word", "tenant", "created_by", "created_at")
    list_filter = ("tenant",)
    search_fields = ("word", "created_by__email", "tenant__name")
    list_select_related = ("tenant", "created_by")
    autocomplete_fields = ("tenant", "created_by")
    ordering = ("word",)
    readonly_fields = _IDENTITY_FIELDS


@admin.register(SafeZone)
class SafeZoneAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "device", "radius_m", "lat", "lng", "created_by")
    list_filter = ("tenant",)
    search_fields = ("name", "address", "tenant__name", "device__name", "created_by__email")
    list_select_related = ("tenant", "device", "created_by")
    autocomplete_fields = ("tenant", "device", "created_by")
    ordering = ("name",)
    readonly_fields = _IDENTITY_FIELDS


@admin.register(DevicePairing)
class DevicePairingAdmin(admin.ModelAdmin):
    list_display = ("device", "tenant", "status", "expires_at", "completed_by", "created_at")
    list_filter = ("status", "tenant")
    search_fields = ("device__name", "completed_by__email", "tenant__name")
    list_select_related = ("device", "tenant", "completed_by")
    autocomplete_fields = ("device", "tenant", "completed_by")
    ordering = ("-created_at",)
    readonly_fields = (*_IDENTITY_FIELDS, "pairing_code", "pairing_token")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "tenant",
                    "device",
                    "status",
                    "expires_at",
                    "completed_by",
                    "created_at",
                    "updated_at",
                    "id",
                ),
            },
        ),
        (
            "Credentials",
            {
                "classes": ("collapse",),
                "description": "Short-lived pairing secrets. Hidden from the changelist.",
                "fields": ("pairing_code", "pairing_token"),
            },
        ),
    )


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    list_display = (
        "device",
        "tenant",
        "granted_by",
        "consent_version",
        "scope_summary",
        "is_active_consent",
        "granted_at",
        "revoked_at",
    )
    list_filter = (
        ("revoked_at", admin.EmptyFieldListFilter),
        "consent_version",
        "tenant",
    )
    search_fields = ("device__name", "granted_by__email", "consent_version")
    list_select_related = ("device", "tenant", "granted_by")
    autocomplete_fields = ("device", "tenant", "granted_by")
    ordering = ("-granted_at",)
    readonly_fields = (*_IDENTITY_FIELDS, "granted_at", "ip_address")

    @admin.display(description="Scopes")
    def scope_summary(self, obj: ConsentRecord) -> str:
        scopes = obj.scopes if isinstance(obj.scopes, list) else []
        return ", ".join(str(scope) for scope in scopes)

    @admin.display(description="Active", boolean=True)
    def is_active_consent(self, obj: ConsentRecord) -> bool:
        return obj.revoked_at is None


@admin.register(ScreenShareSession)
class ScreenShareSessionAdmin(admin.ModelAdmin):
    list_display = (
        "device",
        "requested_by",
        "tenant",
        "status",
        "requested_at",
        "started_at",
        "ended_at",
    )
    list_filter = ("status", "tenant")
    search_fields = (
        "device__name",
        "requested_by__email",
        "ended_reason",
        "tenant__name",
    )
    list_select_related = ("device", "requested_by", "tenant")
    autocomplete_fields = ("device", "requested_by", "tenant")
    readonly_fields = _IDENTITY_FIELDS
    date_hierarchy = "requested_at"
