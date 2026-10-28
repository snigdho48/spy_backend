"""Per-device authorization helpers (BOLA defense).

Authorized readers of a device's events / snapshots / detail:
- the device owner (monitored account), or
- a workspace member with OWNER / ADMIN / MONITOR role.

VIEWER membership alone is not enough to read another member's device data.
There is no separate per-device assignment table today; "assigned" access is
expressed via those monitor roles on the workspace membership model.
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet

from apps.accounts.infrastructure.models.user import User
from apps.devices.infrastructure.models.device import Device
from apps.tenants.infrastructure.models.membership import TenantMembership
from apps.tenants.infrastructure.models.tenant import Tenant
from core.domain.exceptions import EntityNotFoundError, PermissionDeniedError

MONITOR_ROLES = (
    TenantMembership.Role.OWNER,
    TenantMembership.Role.ADMIN,
    TenantMembership.Role.MONITOR,
)


class DeviceAccessService:
    def user_can_access_device(self, user: User, device: Device) -> bool:
        if device.owner_id == user.id:
            return True
        membership = TenantMembership.objects.filter(
            user=user, tenant_id=device.tenant_id
        ).first()
        return bool(membership and membership.role in MONITOR_ROLES)

    def ensure_can_access_device(self, *, user: User, device: Device) -> None:
        if not self.user_can_access_device(user, device):
            raise PermissionDeniedError(
                "Not authorized to access this device's data"
            )

    def get_accessible_device(
        self, *, user: User, tenant: Tenant, device_id
    ) -> Device:
        """Return the device if it is in *tenant* and the user may access it.

        Raises EntityNotFoundError when the device is absent from the tenant
        (avoid leaking existence) and PermissionDeniedError when present but
        the caller lacks authorization.
        """
        device = (
            Device.objects.filter(tenant=tenant, pk=device_id)
            .select_related("owner", "tenant")
            .first()
        )
        if not device:
            raise EntityNotFoundError("Device not found")
        self.ensure_can_access_device(user=user, device=device)
        return device

    def accessible_devices_qs(self, *, user: User, tenant: Tenant) -> QuerySet[Device]:
        membership = TenantMembership.objects.filter(user=user, tenant=tenant).first()
        if membership and membership.role in MONITOR_ROLES:
            return Device.objects.filter(tenant=tenant)
        return Device.objects.filter(tenant=tenant, owner=user)

    def accessible_device_ids(
        self, *, user: User, tenant: Tenant
    ) -> list[UUID]:
        return list(
            self.accessible_devices_qs(user=user, tenant=tenant).values_list(
                "id", flat=True
            )
        )

    def filter_requested_device_ids(
        self, *, user: User, tenant: Tenant, requested: list
    ) -> list[str]:
        """Return lowercase id strings from *requested* the user may access."""
        allowed = {
            str(pk).lower()
            for pk in self.accessible_device_ids(user=user, tenant=tenant)
        }
        out: list[str] = []
        for raw in requested:
            key = str(raw).lower()
            if key in allowed and key not in out:
                out.append(key)
        return out
