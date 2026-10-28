from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.infrastructure.models.user import User
from apps.audit.application.services.audit_service import AuditService
from apps.devices.infrastructure.models.device import ConsentRecord, Device, DevicePairing
from apps.tenants.infrastructure.models.membership import TenantMembership
from apps.tenants.infrastructure.models.tenant import Tenant
from apps.tenants.application.services.workspace_service import SubscriptionService, WorkspaceService
from core.domain.exceptions import (
    ConsentRequiredError,
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from core.middleware.audit import get_audit_context


def normalize_pairing_code(pairing_code: str) -> str:
    cleaned = pairing_code.strip().upper().replace("-", "")
    if len(cleaned) == 6 and cleaned.isalnum():
        return f"{cleaned[:3]}-{cleaned[3:]}"
    return pairing_code.strip().upper()


class DevicePairingService:
    def initiate_pairing(
        self,
        *,
        user: User,
        device_name: str,
        platform: str,
        device_fingerprint: str,
    ) -> DevicePairing:
        if platform not in dict(Device.Platform.choices):
            raise ValidationError(f"Invalid platform: {platform}")

        staging_tenant = WorkspaceService().get_or_create_staging_tenant(user)

        with transaction.atomic():
            device, _ = Device.objects.update_or_create(
                tenant=staging_tenant,
                device_fingerprint=device_fingerprint,
                defaults={
                    "owner": user,
                    "name": device_name,
                    "platform": platform,
                    "status": Device.Status.PENDING,
                },
            )
            pairing, _ = DevicePairing.objects.update_or_create(
                device=device,
                defaults={
                    "tenant": staging_tenant,
                    "status": DevicePairing.Status.PENDING,
                    "expires_at": timezone.now()
                    + timezone.timedelta(seconds=settings.PAIRING_CODE_TTL_SECONDS),
                },
            )

        AuditService().log(
            tenant=staging_tenant,
            actor=user,
            action="device.pairing.initiated",
            resource_type="device",
            resource_id=device.id,
            metadata={"pairing_code": pairing.pairing_code},
        )
        return pairing

    def complete_pairing(
        self,
        *,
        user: User,
        tenant: Tenant,
        pairing_code: str,
        consent_scopes: list[str],
        consent_version: str,
    ) -> tuple[Device, ConsentRecord]:
        invalid_scopes = set(consent_scopes) - settings.VALID_CONSENT_SCOPES
        if invalid_scopes:
            raise ValidationError(f"Invalid consent scopes: {', '.join(invalid_scopes)}")

        normalized_code = normalize_pairing_code(pairing_code)
        pairing = (
            DevicePairing.objects.select_related("device")
            .filter(pairing_code=normalized_code)
            .first()
        )
        if not pairing:
            raise EntityNotFoundError("Invalid pairing code")
        if pairing.is_expired or pairing.status != DevicePairing.Status.PENDING:
            raise ValidationError("Pairing code has expired")

        membership = TenantMembership.objects.filter(user=user, tenant=tenant).first()
        if not membership or membership.role not in (
            TenantMembership.Role.OWNER,
            TenantMembership.Role.ADMIN,
            TenantMembership.Role.MONITOR,
        ):
            raise PermissionDeniedError("Insufficient permissions to complete pairing")

        SubscriptionService().ensure_tenant_can_add_device(tenant)

        ctx = get_audit_context()
        with transaction.atomic():
            device = pairing.device

            if device.tenant_id != tenant.id:
                if Device.objects.filter(
                    tenant=tenant,
                    device_fingerprint=device.device_fingerprint,
                ).exclude(pk=device.pk).exists():
                    raise ValidationError(
                        "This device is already registered in your workspace"
                    )
                device.tenant = tenant
                pairing.tenant = tenant

            device.status = Device.Status.ACTIVE
            device.save(update_fields=["tenant", "status", "updated_at"])

            pairing.status = DevicePairing.Status.COMPLETED
            pairing.completed_by = user
            pairing.save(update_fields=["tenant", "status", "completed_by", "updated_at"])

            ConsentRecord.objects.filter(device=device, revoked_at__isnull=True).update(
                revoked_at=timezone.now()
            )
            consent = ConsentRecord.objects.create(
                tenant=tenant,
                device=device,
                granted_by=device.owner,
                scopes=consent_scopes,
                consent_version=consent_version,
                ip_address=ctx.get("ip_address"),
            )

            # If the new consent dropped the screen scope, kick live streams.
            if "screen" not in (consent.scopes or []):
                from apps.devices.application.services.screen_share_service import (
                    ScreenShareService,
                )
                ScreenShareService().terminate_open_for_device(
                    device, reason="consent_revoked", actor=user
                )

        AuditService().log(
            tenant=tenant,
            actor=user,
            action="device.pairing.completed",
            resource_type="device",
            resource_id=device.id,
            metadata={"scopes": consent_scopes},
        )
        return device, consent


class DeviceManagementService:
    MONITOR_ROLES = (
        TenantMembership.Role.OWNER,
        TenantMembership.Role.ADMIN,
        TenantMembership.Role.MONITOR,
    )

    def _get_device_in_tenant(self, *, tenant: Tenant, device_id) -> Device:
        device = Device.objects.filter(tenant=tenant, pk=device_id).first()
        if not device:
            raise EntityNotFoundError("Device not found")
        return device

    def _ensure_can_manage(self, *, user: User, tenant: Tenant, device: Device) -> None:
        if device.tenant_id != tenant.id:
            raise EntityNotFoundError("Device not found")

        if device.owner_id == user.id:
            return

        membership = TenantMembership.objects.filter(user=user, tenant=tenant).first()
        if not membership or membership.role not in self.MONITOR_ROLES:
            raise PermissionDeniedError("Insufficient permissions to manage this device")

    def set_photo_url(
        self, *, user: User, tenant: Tenant, device_id, photo_url: str
    ) -> Device:
        """Store an https photo URL only — never fetch or proxy the image."""
        device = self._get_device_in_tenant(tenant=tenant, device_id=device_id)
        self._ensure_can_manage(user=user, tenant=tenant, device=device)

        cleaned = (photo_url or "").strip()
        if cleaned:
            parsed = urlparse(cleaned)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValidationError(
                    "photo_url must be an https URL (photos are not proxied)"
                )
            if parsed.username or parsed.password:
                raise ValidationError("photo_url must not include credentials")
            if len(cleaned) > 2048:
                raise ValidationError("photo_url cannot exceed 2048 characters")
        else:
            cleaned = ""

        device.photo_url = cleaned
        device.save(update_fields=["photo_url", "updated_at"])
        AuditService().log(
            tenant=tenant,
            actor=user,
            action="device.photo_updated",
            resource_type="device",
            resource_id=device.id,
            metadata={"has_photo": bool(cleaned)},
        )
        return device

    def disconnect_device(self, *, user: User, tenant: Tenant, device_id) -> Device:
        device = self._get_device_in_tenant(tenant=tenant, device_id=device_id)
        self._ensure_can_manage(user=user, tenant=tenant, device=device)

        with transaction.atomic():
            ConsentRecord.objects.filter(device=device, revoked_at__isnull=True).update(
                revoked_at=timezone.now()
            )
            device.status = Device.Status.REVOKED
            device.save(update_fields=["status", "updated_at"])

        # Screen consent is gone — close any live screen WS streams.
        from apps.devices.application.services.screen_share_service import (
            ScreenShareService,
        )
        ScreenShareService().terminate_open_for_device(
            device, reason="consent_revoked", actor=user
        )

        AuditService().log(
            tenant=tenant,
            actor=user,
            action="device.disconnected",
            resource_type="device",
            resource_id=device.id,
        )
        return device

    def delete_device(self, *, user: User, tenant: Tenant, device_id) -> None:
        device = self._get_device_in_tenant(tenant=tenant, device_id=device_id)
        self._ensure_can_manage(user=user, tenant=tenant, device=device)

        device_id_value = device.id
        device_name = device.name

        with transaction.atomic():
            device.delete()

        AuditService().log(
            tenant=tenant,
            actor=user,
            action="device.deleted",
            resource_type="device",
            resource_id=device_id_value,
            metadata={"name": device_name},
        )


class ConsentService:
    def get_active_consent(self, device: Device) -> ConsentRecord | None:
        return (
            ConsentRecord.objects.filter(device=device, revoked_at__isnull=True)
            .order_by("-granted_at")
            .first()
        )

    def validate_event_scope(
        self, device: Device, event_type: str, consent: ConsentRecord | None = None
    ) -> None:
        scope_map = {
            "location": "location",
            "geofence": "location",
            "battery": "battery",
            "network": "network",
            "app_usage": "app_usage",
            "app_inventory": "app_usage",
            "device_info": "device_info",
            "notification": "notifications",
            "call": "call_log",
            "sms": "sms",
            "message": "messaging",
            "sim": "sim",
            "contact": "contacts",
            "device": "telemetry",
            "sos": "sos",
        }
        prefix = event_type.split(".")[0]
        required_scope = scope_map.get(prefix)
        if not required_scope:
            return

        if consent is None:
            consent = self.get_active_consent(device)
        if not consent or not consent.has_scope(required_scope):
            raise ConsentRequiredError(
                f"Device has not granted '{required_scope}' consent scope"
            )

    def revoke_consent(self, *, device: Device, user: User) -> None:
        DeviceManagementService().disconnect_device(
            user=user,
            tenant=device.tenant,
            device_id=device.id,
        )
