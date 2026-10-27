"""Django admin for the audit trail.

Metadata can contain operational detail such as a pairing code, so it is
kept off the changelist. Rows are inspect-only.
"""

from django.contrib import admin

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "action",
        "resource_type",
        "resource_id",
        "actor",
        "tenant",
        "ip_address",
        "created_at",
    )
    list_filter = ("action", "resource_type", "tenant")
    search_fields = ("action", "resource_type", "actor__email", "ip_address")
    list_select_related = ("actor", "tenant")
    date_hierarchy = "created_at"
    show_full_result_count = False
    show_facets = admin.ShowFacets.NEVER
    readonly_fields = tuple(field.name for field in AuditLog._meta.concrete_fields)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "tenant",
                    "actor",
                    "action",
                    "resource_type",
                    "resource_id",
                    "ip_address",
                    "user_agent",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
        ("Metadata", {"fields": ("metadata",)}),
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
