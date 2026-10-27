"""Django admin for ingested device events.

Changelists show metadata about the event, not the payload. Payloads can
contain message contents and are limited to the change page. Rows are
inspect-only.
"""

from django.contrib import admin

from apps.events.models import DeviceEvent


@admin.register(DeviceEvent)
class DeviceEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_type",
        "device",
        "tenant",
        "event_timestamp",
        "created_at",
    )
    list_filter = ("event_type", "tenant")
    search_fields = ("event_type", "device__name", "idempotency_key")
    list_select_related = ("device", "tenant")
    date_hierarchy = "event_timestamp"
    show_full_result_count = False
    show_facets = admin.ShowFacets.NEVER
    readonly_fields = tuple(field.name for field in DeviceEvent._meta.concrete_fields)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "tenant",
                    "device",
                    "event_type",
                    "event_timestamp",
                    "idempotency_key",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
        ("Payload", {"fields": ("payload",)}),
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
