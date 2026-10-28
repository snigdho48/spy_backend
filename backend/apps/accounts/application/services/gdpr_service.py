"""GDPR right-to-erasure and right-to-access helpers."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.infrastructure.models.user import User
from apps.devices.infrastructure.models.device import Device
from apps.events.infrastructure.models.event import DeviceEvent
from apps.events.infrastructure.models.snapshots import (
    DeviceAppInventorySnapshot,
    DeviceContactSnapshot,
)
from apps.tenants.application.services.workspace_service import WorkspaceService
from apps.tenants.infrastructure.models.membership import TenantMembership
from apps.tenants.infrastructure.models.tenant import Tenant
from core.crypto.field_encryption import decrypt_contacts, decrypt_payload
from core.domain.exceptions import ValidationError

logger = logging.getLogger(__name__)

EVENT_PAGE_SIZE = 200


class GdprService:
    def delete_account(self, user: User) -> dict:
        """Hard-delete the user and cascade owned devices / memberships.

        - Owned devices (and their events/snapshots/consents via CASCADE) go away.
        - Memberships are removed.
        - Tenants the user solely owned (non-staging) are deleted when empty.
        - AuditLog.actor is SET_NULL so history remains without PII link.
        """
        if not user.is_active and user.email.startswith("deleted+"):
            raise ValidationError("Account already deleted")

        owned_device_ids = list(
            Device.objects.filter(owner=user).values_list("id", flat=True)
        )
        membership_tenant_ids = list(
            TenantMembership.objects.filter(user=user).values_list(
                "tenant_id", flat=True
            )
        )

        with transaction.atomic():
            # Revoke JWT blacklist entries belonging to this user if present.
            try:
                from rest_framework_simplejwt.token_blacklist.models import (
                    OutstandingToken,
                )

                OutstandingToken.objects.filter(user=user).delete()
            except Exception:
                pass

            Device.objects.filter(owner=user).delete()
            TenantMembership.objects.filter(user=user).delete()

            # Drop staging tenant(s) for this user.
            Tenant.objects.filter(
                slug=f"{WorkspaceService.STAGING_SLUG_PREFIX}{user.id}"
            ).delete()

            # Delete workspaces that no longer have any members.
            for tenant_id in membership_tenant_ids:
                if not TenantMembership.objects.filter(tenant_id=tenant_id).exists():
                    Tenant.objects.filter(pk=tenant_id).delete()

            user_id = user.id
            email = user.email
            user.delete()

        logger.info(
            "Account deleted user_id=%s devices=%s",
            user_id,
            len(owned_device_ids),
        )
        return {
            "deleted_user_id": str(user_id),
            "deleted_email": email,
            "devices_deleted": len(owned_device_ids),
        }

    def iter_export_chunks(self, user: User) -> Iterator[str]:
        """Yield JSON text chunks for a streaming export response."""
        yield '{"user":'
        yield json.dumps(
            {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "exported_at": timezone.now().isoformat(),
            },
            default=str,
        )
        yield ',"devices":['

        devices = list(
            Device.objects.filter(owner=user)
            .select_related("tenant")
            .order_by("created_at")
        )
        for i, device in enumerate(devices):
            if i:
                yield ","
            yield json.dumps(self._device_export(device), default=str)
        yield "]}"

    def _device_export(self, device: Device) -> dict[str, Any]:
        contact_snap = DeviceContactSnapshot.objects.filter(device=device).first()
        app_snap = DeviceAppInventorySnapshot.objects.filter(device=device).first()

        events: list[dict] = []
        qs = DeviceEvent.objects.filter(device=device).order_by("event_timestamp")
        for event in qs.iterator(chunk_size=EVENT_PAGE_SIZE):
            events.append(
                {
                    "id": str(event.id),
                    "event_type": event.event_type,
                    "payload": decrypt_payload(event.payload or {}),
                    "event_timestamp": event.event_timestamp.isoformat(),
                    "created_at": event.created_at.isoformat(),
                }
            )

        return {
            "id": str(device.id),
            "name": device.name,
            "platform": device.platform,
            "status": device.status,
            "tenant_id": str(device.tenant_id),
            "tenant_name": device.tenant.name,
            "created_at": device.created_at.isoformat(),
            "contact_snapshot": (
                {
                    "contact_count": contact_snap.contact_count,
                    "captured_at": contact_snap.captured_at.isoformat(),
                    "contacts": decrypt_contacts(contact_snap.contacts or []),
                }
                if contact_snap
                else None
            ),
            "app_inventory_snapshot": (
                {
                    "app_count": app_snap.app_count,
                    "captured_at": app_snap.captured_at.isoformat(),
                    "apps": app_snap.apps,
                }
                if app_snap
                else None
            ),
            "events": events,
        }
