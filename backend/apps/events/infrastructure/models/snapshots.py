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


class DeviceAppUsageSnapshot(TenantScopedModel):
    """Latest app-usage / screen-time snapshot for a device.

    ``apps`` is a list of ``{"package", "app_name", "foreground_ms", "launches"}``
    entries describing the most recent reporting window. Historical windows stay
    in the event feed (``app_usage.snapshot``) for range aggregation.
    """

    device = models.OneToOneField(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="app_usage_snapshot",
    )
    apps = models.JSONField(default=list)
    app_count = models.PositiveIntegerField(default=0)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    source_event = models.ForeignKey(
        "events.DeviceEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    captured_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "events_device_app_usage_snapshot"
        indexes = [
            models.Index(fields=["tenant", "-captured_at"]),
        ]

    def __str__(self) -> str:
        return f"app_usage@{self.device_id} ({self.app_count})"


class DeviceTelemetrySnapshot(TenantScopedModel):
    """Latest device telemetry (battery, charging, network, storage, ram)."""

    device = models.OneToOneField(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="telemetry_snapshot",
    )
    battery_pct = models.IntegerField(null=True, blank=True)
    charging = models.BooleanField(null=True, blank=True)
    network_type = models.CharField(max_length=32, blank=True, default="")
    storage_free = models.BigIntegerField(null=True, blank=True)
    storage_total = models.BigIntegerField(null=True, blank=True)
    ram_free = models.BigIntegerField(null=True, blank=True)
    ram_total = models.BigIntegerField(null=True, blank=True)
    metrics = models.JSONField(default=dict)
    source_event = models.ForeignKey(
        "events.DeviceEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    captured_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "events_device_telemetry_snapshot"
        indexes = [
            models.Index(fields=["tenant", "-captured_at"]),
        ]

    def __str__(self) -> str:
        return f"telemetry@{self.device_id} ({self.battery_pct}%)"
