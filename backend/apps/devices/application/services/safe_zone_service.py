from __future__ import annotations

from uuid import UUID

from django.db.models import Q, QuerySet

from apps.accounts.application.services.auth_service import AuthenticationService
from apps.accounts.infrastructure.models.user import User
from apps.audit.application.services.audit_service import AuditService
from apps.devices.infrastructure.models.device import Device, SafeZone
from apps.tenants.application.services.workspace_service import WorkspaceService
from apps.tenants.infrastructure.models.membership import TenantMembership
from core.domain.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)

MANAGE_ROLES = (
    TenantMembership.Role.OWNER,
    TenantMembership.Role.ADMIN,
    TenantMembership.Role.MONITOR,
)

MIN_RADIUS_M = 10
MAX_RADIUS_M = 50_000
MAX_NAME_LEN = 128
MAX_ADDRESS_LEN = 255


class SafeZoneService:
    def list_for_user(self, user: User) -> QuerySet[SafeZone]:
        membership = AuthenticationService().get_user_membership(user)
        owned = Device.objects.filter(
            owner=user, status=Device.Status.ACTIVE
        ).only("id", "tenant_id")
        owned_tenant_ids = set(owned.values_list("tenant_id", flat=True))

        # Monitored phones live on the family workspace. The device owner often
        # still has their own empty personal tenant membership — prefer zones
        # that apply to their linked devices in that case.
        monitored_elsewhere = bool(owned_tenant_ids) and (
            membership is None
            or membership.tenant_id not in owned_tenant_ids
            or WorkspaceService.is_staging_tenant(membership.tenant)
        )
        if monitored_elsewhere:
            device_ids = list(owned.values_list("id", flat=True))
            return (
                SafeZone.objects.filter(tenant_id__in=owned_tenant_ids)
                .filter(Q(device_id__isnull=True) | Q(device_id__in=device_ids))
                .select_related("device", "created_by")
                .order_by("name")
            )

        if (
            membership
            and membership.role in MANAGE_ROLES
            and not WorkspaceService.is_staging_tenant(membership.tenant)
        ):
            return (
                SafeZone.objects.filter(tenant=membership.tenant)
                .select_related("device", "created_by")
                .order_by("name")
            )

        raise PermissionDeniedError(
            "Only workspace monitors or monitored device owners can list safe zones"
        )

    def create(
        self,
        *,
        user: User,
        name: str,
        lat: float,
        lng: float,
        radius_m: int = 100,
        address: str = "",
        device_id: UUID | None = None,
        enabled: bool = True,
    ) -> SafeZone:
        membership = self._require_manage_membership(user)
        tenant = membership.tenant
        cleaned = self._validate_fields(
            name=name,
            lat=lat,
            lng=lng,
            radius_m=radius_m,
            address=address,
        )
        device = self._resolve_device(tenant=tenant, device_id=device_id)

        if SafeZone.objects.filter(tenant=tenant, name__iexact=cleaned["name"]).exists():
            raise ValidationError("A safe zone with this name already exists")

        zone = SafeZone.objects.create(
            tenant=tenant,
            name=cleaned["name"],
            address=cleaned["address"],
            lat=cleaned["lat"],
            lng=cleaned["lng"],
            radius_m=cleaned["radius_m"],
            enabled=bool(enabled),
            created_by=user,
            device=device,
        )
        AuditService().log(
            tenant=tenant,
            actor=user,
            action="safe_zone.created",
            resource_type="safe_zone",
            resource_id=zone.id,
            metadata={
                "name": zone.name,
                "device_id": str(device.id) if device else None,
                "radius_m": zone.radius_m,
            },
        )
        return zone

    def update(
        self,
        *,
        user: User,
        zone_id: UUID,
        **fields,
    ) -> SafeZone:
        membership = self._require_manage_membership(user)
        zone = (
            SafeZone.objects.filter(tenant=membership.tenant, pk=zone_id)
            .select_related("device")
            .first()
        )
        if not zone:
            raise EntityNotFoundError("Safe zone not found")

        name = fields.get("name", zone.name)
        lat = fields.get("lat", zone.lat)
        lng = fields.get("lng", zone.lng)
        radius_m = fields.get("radius_m", zone.radius_m)
        address = fields.get("address", zone.address)
        cleaned = self._validate_fields(
            name=name,
            lat=lat,
            lng=lng,
            radius_m=radius_m,
            address=address,
        )

        if (
            SafeZone.objects.filter(
                tenant=membership.tenant, name__iexact=cleaned["name"]
            )
            .exclude(pk=zone.pk)
            .exists()
        ):
            raise ValidationError("A safe zone with this name already exists")

        if "device_id" in fields:
            zone.device = self._resolve_device(
                tenant=membership.tenant, device_id=fields["device_id"]
            )

        zone.name = cleaned["name"]
        zone.address = cleaned["address"]
        zone.lat = cleaned["lat"]
        zone.lng = cleaned["lng"]
        zone.radius_m = cleaned["radius_m"]
        if "enabled" in fields:
            zone.enabled = bool(fields["enabled"])
        zone.save()

        AuditService().log(
            tenant=membership.tenant,
            actor=user,
            action="safe_zone.updated",
            resource_type="safe_zone",
            resource_id=zone.id,
            metadata={"name": zone.name, "radius_m": zone.radius_m},
        )
        return zone

    def delete(self, *, user: User, zone_id: UUID) -> None:
        membership = self._require_manage_membership(user)
        zone = SafeZone.objects.filter(
            tenant=membership.tenant, pk=zone_id
        ).first()
        if not zone:
            raise EntityNotFoundError("Safe zone not found")

        zone_id_value = zone.id
        zone_name = zone.name
        zone.delete()

        AuditService().log(
            tenant=membership.tenant,
            actor=user,
            action="safe_zone.deleted",
            resource_type="safe_zone",
            resource_id=zone_id_value,
            metadata={"name": zone_name},
        )

    def resolve_for_device(
        self,
        *,
        device: Device,
        zone_id: str | UUID | None = None,
        zone_name: str | None = None,
    ) -> SafeZone:
        qs = SafeZone.objects.filter(tenant=device.tenant).filter(
            Q(device_id__isnull=True) | Q(device_id=device.id)
        )
        if zone_id:
            zone = qs.filter(pk=zone_id).first()
            if not zone:
                raise ValidationError("Unknown safe zone id")
            return zone
        if zone_name:
            cleaned = zone_name.strip()
            # Accept either raw name or "Safe Zone: Name"
            if cleaned.lower().startswith("safe zone:"):
                cleaned = cleaned.split(":", 1)[1].strip()
            zone = qs.filter(name__iexact=cleaned).first()
            if not zone:
                raise ValidationError("Unknown safe zone name")
            return zone
        raise ValidationError("zone_id or zone_name is required")

    def enrich_location_payload(self, device: Device, payload: dict) -> dict:
        """Resolve optional zone_id / required geofence zone refs. Mutates a copy."""
        out = dict(payload)
        zone_id = out.get("zone_id")
        zone_name = out.get("zone_name")
        if not zone_id and not zone_name:
            return out

        zone = self.resolve_for_device(
            device=device, zone_id=zone_id, zone_name=zone_name
        )
        out["zone_id"] = str(zone.id)
        out["zone_name"] = zone.display_label
        if not out.get("place_name"):
            out["place_name"] = zone.display_label
        if not out.get("address") and zone.address:
            out["address"] = zone.address
        return out

    def _require_manage_membership(self, user: User) -> TenantMembership:
        membership = AuthenticationService().get_user_membership(user)
        if (
            not membership
            or membership.role not in MANAGE_ROLES
            or WorkspaceService.is_staging_tenant(membership.tenant)
        ):
            raise PermissionDeniedError(
                "Only workspace owners, admins or monitors can manage safe zones"
            )
        return membership

    def _resolve_device(self, *, tenant, device_id: UUID | None) -> Device | None:
        if device_id is None:
            return None
        device = Device.objects.filter(tenant=tenant, pk=device_id).first()
        if not device:
            raise EntityNotFoundError("Device not found in this workspace")
        return device

    def _validate_fields(
        self,
        *,
        name: str,
        lat: float,
        lng: float,
        radius_m: int,
        address: str,
    ) -> dict:
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            raise ValidationError("name is required")
        if len(cleaned_name) > MAX_NAME_LEN:
            raise ValidationError(f"name cannot exceed {MAX_NAME_LEN} characters")

        cleaned_address = (address or "").strip()
        if len(cleaned_address) > MAX_ADDRESS_LEN:
            raise ValidationError(f"address cannot exceed {MAX_ADDRESS_LEN} characters")

        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except (TypeError, ValueError) as exc:
            raise ValidationError("lat and lng must be numbers") from exc
        if not -90.0 <= lat_f <= 90.0:
            raise ValidationError("lat must be between -90 and 90")
        if not -180.0 <= lng_f <= 180.0:
            raise ValidationError("lng must be between -180 and 180")

        try:
            radius = int(radius_m)
        except (TypeError, ValueError) as exc:
            raise ValidationError("radius_m must be an integer") from exc
        if radius < MIN_RADIUS_M or radius > MAX_RADIUS_M:
            raise ValidationError(
                f"radius_m must be between {MIN_RADIUS_M} and {MAX_RADIUS_M}"
            )

        return {
            "name": cleaned_name,
            "address": cleaned_address,
            "lat": lat_f,
            "lng": lng_f,
            "radius_m": radius,
        }
