"""Plan-based event / snapshot retention purge (GDPR data-minimisation)."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.events.infrastructure.models.event import DeviceEvent
from apps.events.infrastructure.models.snapshots import (
    DeviceAppInventorySnapshot,
    DeviceContactSnapshot,
)
from apps.tenants.domain.plan_catalog import get_plan
from apps.tenants.infrastructure.models.tenant import Tenant

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 500


class RetentionService:
    """Delete events older than each tenant plan's retention window.

    Snapshots are kept when `captured_at` is still within the window; older
    snapshot rows are removed so stale address-books do not outlive events.
    Idempotent: re-running after a full purge is a no-op.
    """

    def purge_all(self, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict:
        totals = {
            "tenants": 0,
            "events_deleted": 0,
            "contact_snapshots_deleted": 0,
            "app_snapshots_deleted": 0,
        }
        for tenant in Tenant.objects.filter(is_active=True).iterator(chunk_size=100):
            result = self.purge_tenant(tenant, chunk_size=chunk_size)
            if result["events_deleted"] or result["contact_snapshots_deleted"] or result[
                "app_snapshots_deleted"
            ]:
                totals["tenants"] += 1
            totals["events_deleted"] += result["events_deleted"]
            totals["contact_snapshots_deleted"] += result["contact_snapshots_deleted"]
            totals["app_snapshots_deleted"] += result["app_snapshots_deleted"]
        logger.info(
            "Retention purge complete: tenants=%s events=%s contacts=%s apps=%s",
            totals["tenants"],
            totals["events_deleted"],
            totals["contact_snapshots_deleted"],
            totals["app_snapshots_deleted"],
        )
        return totals

    def purge_tenant(
        self, tenant: Tenant, *, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> dict:
        plan = get_plan(tenant.plan) or get_plan(Tenant.Plan.FREE)
        retention_days = plan.event_retention_days if plan else 7
        cutoff = timezone.now() - timedelta(days=retention_days)

        events_deleted = 0
        while True:
            ids = list(
                DeviceEvent.objects.filter(
                    tenant=tenant, event_timestamp__lt=cutoff
                ).values_list("id", flat=True)[:chunk_size]
            )
            if not ids:
                break
            with transaction.atomic():
                deleted, _ = DeviceEvent.objects.filter(id__in=ids).delete()
            events_deleted += deleted
            if len(ids) < chunk_size:
                break

        contact_deleted, _ = DeviceContactSnapshot.objects.filter(
            tenant=tenant, captured_at__lt=cutoff
        ).delete()
        app_deleted, _ = DeviceAppInventorySnapshot.objects.filter(
            tenant=tenant, captured_at__lt=cutoff
        ).delete()

        return {
            "tenant_id": str(tenant.id),
            "retention_days": retention_days,
            "cutoff": cutoff.isoformat(),
            "events_deleted": events_deleted,
            "contact_snapshots_deleted": contact_deleted,
            "app_snapshots_deleted": app_deleted,
        }
