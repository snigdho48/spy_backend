import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.infrastructure.models.base import TenantScopedModel


class Device(TenantScopedModel):
    class Platform(models.TextChoices):
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"
        WEB = "web", "Web"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Pairing"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        REVOKED = "revoked", "Revoked"

    owner = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="owned_devices",
    )
    name = models.CharField(max_length=255)
    platform = models.CharField(max_length=32, choices=Platform.choices)
    device_fingerprint = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    photo_url = models.URLField(max_length=2048, blank=True, default="")

    class Meta:
        db_table = "devices_device"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "device_fingerprint"],
                name="unique_tenant_device_fingerprint",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["owner"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.platform})"

    @property
    def is_paused(self) -> bool:
        """True when an unended pause covers the current time."""
        return self.get_active_pause() is not None

    def get_active_pause(self) -> "SharingPause | None":
        from apps.devices.application.services.sharing_pause_service import (
            SharingPauseService,
        )

        return SharingPauseService().get_active_pause(self)


class SharingPause(TenantScopedModel):
    """Temporary halt of telemetry upload; consent scopes stay unchanged."""

    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="sharing_pauses",
    )
    started_at = models.DateTimeField(db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="created_sharing_pauses",
    )
    reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "devices_sharing_pause"
        indexes = [
            models.Index(fields=["device", "ended_at", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"Pause {self.device_id} until {self.expires_at}"


class WatchlistKeyword(TenantScopedModel):
    """Tenant-scoped safety keyword for SMS/message flagging."""

    word = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="created_watchlist_keywords",
    )

    class Meta:
        db_table = "devices_watchlist_keyword"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "word"],
                name="unique_tenant_watchlist_keyword",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "word"]),
        ]

    def __str__(self) -> str:
        return self.word


class SafeZone(TenantScopedModel):
    """Named geofence area. Optional device FK scopes the zone to one phone."""

    name = models.CharField(max_length=128)
    address = models.CharField(max_length=255, blank=True, default="")
    lat = models.FloatField()
    lng = models.FloatField()
    radius_m = models.PositiveIntegerField(default=100)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="created_safe_zones",
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="safe_zones",
    )

    class Meta:
        db_table = "devices_safe_zone"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="unique_tenant_safe_zone_name",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "device"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.lat}, {self.lng})"

    @property
    def display_label(self) -> str:
        return f"Safe Zone: {self.name}"


class DevicePairing(TenantScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        EXPIRED = "expired", "Expired"

    device = models.OneToOneField(
        Device,
        on_delete=models.CASCADE,
        related_name="pairing",
    )
    pairing_code = models.CharField(max_length=16, unique=True, db_index=True)
    pairing_token = models.CharField(max_length=128, unique=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    expires_at = models.DateTimeField(db_index=True)
    completed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_pairings",
    )

    class Meta:
        db_table = "devices_pairing"

    def __str__(self) -> str:
        return f"{self.status} pairing for {self.device_id}"

    @staticmethod
    def generate_code() -> str:
        chars = string.ascii_uppercase + string.digits
        part = "".join(secrets.choice(chars) for _ in range(6))
        return f"{part[:3]}-{part[3:]}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    def save(self, *args, **kwargs):
        if not self.pairing_code:
            self.pairing_code = self.generate_code()
        if not self.pairing_token:
            self.pairing_token = secrets.token_urlsafe(48)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(
                seconds=settings.PAIRING_CODE_TTL_SECONDS
            )
        super().save(*args, **kwargs)


class ConsentRecord(TenantScopedModel):
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="consent_records",
    )
    granted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="granted_consents",
    )
    scopes = models.JSONField(default=list)
    consent_version = models.CharField(max_length=32)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "devices_consent_record"
        indexes = [
            models.Index(fields=["device", "revoked_at"]),
        ]

    def __str__(self) -> str:
        state = "active" if self.revoked_at is None else "revoked"
        return f"{state} consent for {self.device_id}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def has_scope(self, scope: str) -> bool:
        return self.is_active and scope in self.scopes
