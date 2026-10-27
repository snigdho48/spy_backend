"""Latest-per-device denormalized snapshots for heavy list payloads.

Events remain the source of truth / history. These rows exist so monitors can
read the current contacts / installed-app inventory without paging event history
or shipping megabyte icon blobs.
"""

from django.db import models

from core.infrastructure.models.base import TenantScopedModel


class DeviceContactSnapshot(TenantScopedModel):
    device = models.OneToOneField(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="contact_snapshot",
    )
    contacts = models.JSONField(default=list)
    contact_count = models.PositiveIntegerField(default=0)
    source_event = models.ForeignKey(
        "events.DeviceEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    captured_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "events_device_contact_snapshot"
        indexes = [
            models.Index(fields=["tenant", "-captured_at"]),
        ]

    def __str__(self) -> str:
        return f"contacts@{self.device_id} ({self.contact_count})"


class DeviceAppInventorySnapshot(TenantScopedModel):
    device = models.OneToOneField(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="app_inventory_snapshot",
    )
    apps = models.JSONField(default=list)
    app_count = models.PositiveIntegerField(default=0)
    include_system = models.BooleanField(default=True)
    source_event = models.ForeignKey(
        "events.DeviceEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    captured_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "events_device_app_inventory_snapshot"
        indexes = [
            models.Index(fields=["tenant", "-captured_at"]),
        ]

    def __str__(self) -> str:
        return f"apps@{self.device_id} ({self.app_count})"
