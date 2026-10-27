from django.db import models

from core.infrastructure.models.base import TenantScopedModel


class DeviceEvent(TenantScopedModel):
    device = models.ForeignKey(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="events",
        db_index=True,
    )
    event_type = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True)
    event_timestamp = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "events_device_event"
        indexes = [
            models.Index(fields=["device", "-created_at"]),
            models.Index(fields=["tenant", "-created_at"]),
            models.Index(fields=["event_type", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.event_timestamp}"
