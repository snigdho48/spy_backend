"""Live screen-sharing session model.

A ScreenShareSession is a short-lived, consent-gated negotiation between a
monitor (who requests a live view) and the monitored device (which accepts and
streams frames). Frames themselves are NEVER persisted here — only the session
lifecycle is stored and audited. Live frame/signaling transport happens over
Channels (see ScreenShareConsumer), kept out of the durable event table.
"""

from django.db import models

from core.infrastructure.models.base import TenantScopedModel


class ScreenShareSession(TenantScopedModel):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"
        DENIED = "denied", "Denied"
        EXPIRED = "expired", "Expired"

    device = models.ForeignKey(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="screen_share_sessions",
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="requested_screen_shares",
    )
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
        db_table = "devices_screen_share_session"
        indexes = [
            models.Index(fields=["device", "status"]),
            models.Index(fields=["tenant", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ScreenShare {self.device_id} ({self.status})"

    @property
    def is_open(self) -> bool:
        """True while the session can still carry live frames."""
        return self.status in (self.Status.REQUESTED, self.Status.ACTIVE)
