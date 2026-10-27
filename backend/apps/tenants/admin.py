"""Django admin for tenants and memberships."""

from django.contrib import admin

from apps.tenants.models import Tenant, TenantMembership

_IDENTITY_FIELDS = ("id", "created_at", "updated_at")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "plan", "is_active", "created_at")
    list_filter = ("plan", "is_active")
    search_fields = ("name", "slug")
    ordering = ("name",)
    readonly_fields = _IDENTITY_FIELDS
    date_hierarchy = "created_at"
    fieldsets = (
        (None, {"fields": ("name", "slug", "plan", "is_active")}),
        ("Identity", {"fields": _IDENTITY_FIELDS}),
    )


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "role", "created_at")
    list_filter = ("role", "tenant")
    search_fields = ("user__email", "user__full_name", "tenant__name", "tenant__slug")
    list_select_related = ("user", "tenant")
    autocomplete_fields = ("user", "tenant")
    ordering = ("-created_at",)
    readonly_fields = _IDENTITY_FIELDS
