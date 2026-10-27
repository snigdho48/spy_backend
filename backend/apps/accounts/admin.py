"""Django admin for accounts.

Passwords are changed through Django's admin password form. Refresh-token
identifiers stay off changelist columns.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from apps.accounts.models import RefreshTokenRecord, SocialAccount, User
from apps.tenants.models import TenantMembership

_IDENTITY_FIELDS = ("id", "created_at", "updated_at")


class EmailUserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("email",)


class EmailUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User


class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    extra = 0
    autocomplete_fields = ("tenant",)
    fields = ("tenant", "role", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


class SocialAccountInline(admin.TabularInline):
    model = SocialAccount
    extra = 0
    fields = ("provider", "provider_uid", "email", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = EmailUserChangeForm
    add_form = EmailUserCreationForm
    ordering = ("email",)
    list_display = (
        "email",
        "full_name",
        "is_staff",
        "is_superuser",
        "is_active",
        "created_at",
    )
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("email", "full_name")
    readonly_fields = (*_IDENTITY_FIELDS, "last_login", "last_login_ip")
    filter_horizontal = ("groups", "user_permissions")
    inlines = (TenantMembershipInline, SocialAccountInline)
    date_hierarchy = "created_at"
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name",)}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (
            "Activity",
            {
                "fields": (
                    "last_login",
                    "last_login_ip",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
        ("Identity", {"fields": ("id",)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "full_name",
                    "usable_password",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_superuser",
                    "is_active",
                ),
            },
        ),
    )


@admin.register(RefreshTokenRecord)
class RefreshTokenRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "expires_at",
        "revoked_at",
        "ip_address",
        "created_at",
    )
    list_filter = (("revoked_at", admin.EmptyFieldListFilter), "expires_at")
    search_fields = ("user__email", "ip_address")
    list_select_related = ("user",)
    ordering = ("-created_at",)
    readonly_fields = (
        *_IDENTITY_FIELDS,
        "user",
        "jti",
        "expires_at",
        "replaced_by_jti",
        "ip_address",
        "user_agent",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "user",
                    "expires_at",
                    "revoked_at",
                    "ip_address",
                    "user_agent",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
        (
            "Token identifiers",
            {
                "classes": ("collapse",),
                "description": (
                    "JWT ids for support correlation. Not shown in the changelist."
                ),
                "fields": ("jti", "replaced_by_jti"),
            },
        ),
    )

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "email", "provider_uid", "created_at")
    list_filter = ("provider",)
    search_fields = ("email", "provider_uid", "user__email", "user__full_name")
    list_select_related = ("user",)
    autocomplete_fields = ("user",)
    ordering = ("-created_at",)
    readonly_fields = _IDENTITY_FIELDS
