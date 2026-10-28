"""Create alerts and notify registered monitor push tokens."""

from __future__ import annotations

import logging
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.infrastructure.models.user import User
from apps.alerts.infrastructure.models.alert import Alert, PushToken
from apps.devices.application.services.device_access import DeviceAccessService
from apps.devices.infrastructure.models.device import Device
from apps.tenants.infrastructure.models.tenant import Tenant
from core.domain.exceptions import EntityNotFoundError, PermissionDeniedError

logger = logging.getLogger(__name__)


class AlertService:
    def create_alert(
        self,
        *,
        device: Device,
        alert_type: str,
        title: str,
        body: str = "",
        severity: str = Alert.Severity.INFO,
        metadata: dict | None = None,
    ) -> Alert:
        alert = Alert.objects.create(
            tenant_id=device.tenant_id,
            device=device,
            type=alert_type,
            severity=severity,
            title=title[:255],
            body=body or "",
            metadata=metadata or {},
        )
        self._enqueue_push(alert)
        return alert

    def list_for_user(
        self,
        *,
        user: User,
        tenant: Tenant,
        device_id=None,
        alert_type: str | None = None,
        unread_only: bool = False,
    ) -> QuerySet[Alert]:
        access = DeviceAccessService()
        allowed = access.accessible_device_ids(user=user, tenant=tenant)
        qs = Alert.objects.filter(tenant=tenant, device_id__in=allowed)
        if device_id:
            access.get_accessible_device(
                user=user, tenant=tenant, device_id=device_id
            )
            qs = qs.filter(device_id=device_id)
        if alert_type:
            qs = qs.filter(type=alert_type)
        if unread_only:
            qs = qs.filter(read_at__isnull=True)
        return qs.select_related("device").order_by("-created_at")

    def mark_read(
        self, *, user: User, tenant: Tenant, alert_id
    ) -> Alert:
        alert = (
            Alert.objects.filter(tenant=tenant, pk=alert_id)
            .select_related("device")
            .first()
        )
        if not alert:
            raise EntityNotFoundError("Alert not found")
        DeviceAccessService().ensure_can_access_device(
            user=user, device=alert.device
        )
        if alert.read_at is None:
            alert.read_at = timezone.now()
            alert.save(update_fields=["read_at", "updated_at"])
        return alert

    def mark_all_read(
        self, *, user: User, tenant: Tenant, device_id=None
    ) -> int:
        qs = self.list_for_user(
            user=user, tenant=tenant, device_id=device_id, unread_only=True
        )
        return qs.update(read_at=timezone.now(), updated_at=timezone.now())

    def delete_alert(self, *, user: User, tenant: Tenant, alert_id) -> None:
        alert = (
            Alert.objects.filter(tenant=tenant, pk=alert_id)
            .select_related("device")
            .first()
        )
        if not alert:
            raise EntityNotFoundError("Alert not found")
        # Deletes require monitor-level access (not VIEWER). Owner always ok.
        from apps.tenants.infrastructure.models.membership import TenantMembership
        from apps.devices.application.services.device_access import MONITOR_ROLES

        if alert.device.owner_id != user.id:
            membership = TenantMembership.objects.filter(
                user=user, tenant=tenant
            ).first()
            if not membership or membership.role not in MONITOR_ROLES:
                raise PermissionDeniedError(
                    "Not authorized to delete this alert"
                )
        else:
            DeviceAccessService().ensure_can_access_device(
                user=user, device=alert.device
            )
        alert.delete()

    def _enqueue_push(self, alert: Alert) -> None:
        try:
            from apps.alerts.tasks import push_alert_notification

            push_alert_notification.delay(str(alert.id))
        except Exception:
            # Broker unavailable (e.g. tests without Celery) — fail soft.
            logger.exception("Failed to enqueue push for alert %s", alert.id)

    # ---- generation helpers ---------------------------------------------

    def on_geofence_transition(
        self, *, device: Device, zone, transition: str, distance_m: float
    ) -> Alert:
        alert_type = (
            Alert.Type.GEOFENCE_ENTER
            if transition == "enter"
            else Alert.Type.GEOFENCE_EXIT
        )
        verb = "entered" if transition == "enter" else "exited"
        return self.create_alert(
            device=device,
            alert_type=alert_type,
            severity=Alert.Severity.WARNING,
            title=f"{device.name} {verb} {zone.name}",
            body=f"Device is now {'inside' if transition == 'enter' else 'outside'} "
            f"safe zone '{zone.name}' (≈{distance_m:.0f} m from centre).",
            metadata={
                "zone_id": str(zone.id),
                "zone_name": zone.name,
                "transition": transition,
                "distance_m": distance_m,
            },
        )

    def on_app_installed(
        self, *, device: Device, package: str, app_name: str = ""
    ) -> Alert:
        label = app_name or package
        return self.create_alert(
            device=device,
            alert_type=Alert.Type.APP_INSTALLED,
            severity=Alert.Severity.INFO,
            title=f"New app installed: {label}",
            body=f"Package {package} was added to {device.name}.",
            metadata={"package": package, "app_name": label},
        )

    def on_sim_changed(self, *, device: Device, payload: dict) -> Alert:
        return self.create_alert(
            device=device,
            alert_type=Alert.Type.SIM_CHANGED,
            severity=Alert.Severity.HIGH,
            title=f"SIM change on {device.name}",
            body="The device reported a SIM / telephony identity change.",
            metadata={"payload": payload},
        )

    def on_low_battery(
        self, *, device: Device, battery_pct: int, charging: bool
    ) -> Alert | None:
        # Debounce: skip if an unread low_battery alert already exists.
        if Alert.objects.filter(
            device=device,
            type=Alert.Type.LOW_BATTERY,
            read_at__isnull=True,
        ).exists():
            return None
        return self.create_alert(
            device=device,
            alert_type=Alert.Type.LOW_BATTERY,
            severity=Alert.Severity.WARNING,
            title=f"Low battery on {device.name}",
            body=f"Battery at {battery_pct}% and not charging.",
            metadata={"battery_pct": battery_pct, "charging": charging},
        )

    def on_sos(self, *, device: Device, payload: dict) -> Alert:
        return self.create_alert(
            device=device,
            alert_type=Alert.Type.SOS,
            severity=Alert.Severity.CRITICAL,
            title=f"SOS from {device.name}",
            body="The device triggered a panic / SOS event.",
            metadata={"payload": payload},
        )


class PushTokenService:
    def register(
        self,
        *,
        user: User,
        tenant: Tenant,
        token: str,
        platform: str = PushToken.Platform.ANDROID,
    ) -> PushToken:
        cleaned = (token or "").strip()
        if not cleaned or len(cleaned) > 512:
            from core.domain.exceptions import ValidationError

            raise ValidationError("token is required (max 512 chars)")
        if platform not in dict(PushToken.Platform.choices):
            from core.domain.exceptions import ValidationError

            raise ValidationError(f"Invalid platform: {platform}")
        obj, _ = PushToken.objects.update_or_create(
            tenant=tenant,
            token=cleaned,
            defaults={"user": user, "platform": platform},
        )
        return obj

    def unregister(
        self, *, user: User, tenant: Tenant, token: str | None = None, token_id=None
    ) -> int:
        qs = PushToken.objects.filter(tenant=tenant, user=user)
        if token_id:
            qs = qs.filter(pk=token_id)
        elif token:
            qs = qs.filter(token=token)
        else:
            from core.domain.exceptions import ValidationError

            raise ValidationError("token or token_id is required")
        deleted, _ = qs.delete()
        return deleted

    def tokens_for_device_monitors(self, device: Device) -> list[PushToken]:
        """Tokens belonging to the device owner + workspace monitors."""
        from apps.tenants.infrastructure.models.membership import TenantMembership
        from apps.devices.application.services.device_access import MONITOR_ROLES

        user_ids = {device.owner_id}
        user_ids.update(
            TenantMembership.objects.filter(
                tenant_id=device.tenant_id, role__in=MONITOR_ROLES
            ).values_list("user_id", flat=True)
        )
        return list(
            PushToken.objects.filter(
                tenant_id=device.tenant_id, user_id__in=user_ids
            )
        )
