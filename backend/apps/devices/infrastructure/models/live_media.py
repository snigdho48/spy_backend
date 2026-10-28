"""Live camera / microphone session model.

Mirrors ScreenShareSession: short-lived negotiation + Channels transport.
Frames/audio are NEVER persisted — only session lifecycle is audited.
Unlike screen share, camera/mic sessions auto-start on the monitored device
when the corresponding enrollment consent scope is active (no per-session
in-app prompt); the OS privacy indicator remains unavoidable.
"""

from django.db import models

from core.infrastructure.models.base import TenantScopedModel


class LiveMediaSession(TenantScopedModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"
        DENIED = "denied", "Denied"
        EXPIRED = "expired", "Expired"

    class MediaKind(models.TextChoices):
        CAMERA = "camera", "Camera"
        MICROPHONE = "microphone", "Microphone"
        BOTH = "both", "Camera + Microphone"

    device = models.ForeignKey(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="live_media_sessions",
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="requested_live_media",
    )
    media_kind = models.CharField(
        max_length=16,
        choices=MediaKind.choices,
        default=MediaKind.CAMERA,
        db_index=True,
    )
    # Preferred camera facing for camera/both sessions: front | back.
    camera_facing = models.CharField(max_length=8, default="back", blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.REQUESTED,
        db_index=True,
    )
    requested_at = models.DateTimeField(db_index=True)
    started_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ended_reason = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "devices_live_media_session"
        indexes = [
            models.Index(fields=["device", "status"]),
            models.Index(fields=["tenant", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"LiveMedia {self.media_kind} {self.device_id} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status in (self.Status.REQUESTED, self.Status.ACTIVE)

    def required_scopes(self) -> set[str]:
        if self.media_kind == self.MediaKind.CAMERA:
            return {"camera"}
        if self.media_kind == self.MediaKind.MICROPHONE:
            return {"microphone"}
        return {"camera", "microphone"}
