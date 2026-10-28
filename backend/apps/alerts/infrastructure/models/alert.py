"""Alert and push-token models for monitor notifications."""

from django.db import models

from core.infrastructure.models.base import TenantScopedModel


class Alert(TenantScopedModel):
    class Type(models.TextChoices):
        GEOFENCE_ENTER = "geofence_enter", "Geofence enter"
        GEOFENCE_EXIT = "geofence_exit", "Geofence exit"
        APP_INSTALLED = "app_installed", "App installed"
        SIM_CHANGED = "sim_changed", "SIM changed"
        LOW_BATTERY = "low_battery", "Low battery"
        SOS = "sos", "SOS"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    device = models.ForeignKey(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="alerts",
        db_index=True,
    )
    type = models.CharField(max_length=32, choices=Type.choices, db_index=True)
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.INFO, db_index=True
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "alerts_alert"
        indexes = [
            models.Index(fields=["device", "-created_at"]),
            models.Index(fields=["tenant", "-created_at"]),
            models.Index(fields=["type", "created_at"]),
            models.Index(fields=["tenant", "read_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.type}: {self.title}"

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


class PushToken(TenantScopedModel):
    """FCM registration token for a monitor / owner user."""

    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        WEB = "web", "Web"

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="push_tokens",
    )
    token = models.CharField(max_length=512)
    platform = models.CharField(
        max_length=16, choices=Platform.choices, default=Platform.ANDROID
    )

    class Meta:
        db_table = "alerts_push_token"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "token"],
                name="unique_tenant_push_token",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "tenant"]),
        ]

    def __str__(self) -> str:
        return f"{self.platform} token for {self.user_id}"
