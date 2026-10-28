"""Django admin for alerts and push tokens."""

from django.contrib import admin

from apps.alerts.models import Alert, PushToken

_IDENTITY_FIELDS = ("id", "created_at", "updated_at")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = (
        "type",
        "severity",
        "title",
        "device",
        "tenant",
        "read_at",
        "created_at",
    )
    list_filter = ("type", "severity", "tenant")
    search_fields = ("title", "body", "device__name")
    list_select_related = ("device", "tenant")
    date_hierarchy = "created_at"
    readonly_fields = (*_IDENTITY_FIELDS, "read_at")
    show_full_result_count = False

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(PushToken)
class PushTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "tenant", "token_prefix", "created_at")
    list_filter = ("platform", "tenant")
    search_fields = ("user__email", "token")
    list_select_related = ("user", "tenant")
    readonly_fields = _IDENTITY_FIELDS

    @admin.display(description="Token")
    def token_prefix(self, obj: PushToken) -> str:
        token = obj.token or ""
        return f"{token[:12]}…" if len(token) > 12 else token
