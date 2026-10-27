from __future__ import annotations

from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from apps.accounts.infrastructure.models.user import User
from apps.audit.application.services.audit_service import AuditService
from apps.devices.infrastructure.models.device import Device, SharingPause
from core.domain.exceptions import (
    ConflictError,
    EntityNotFoundError,
    ValidationError,
)

ALLOWED_PAUSE_MINUTES = frozenset({15, 30, 60, 120, 240})
MAX_PAUSE_MINUTES = 24 * 60


class SharingPauseService:
    def get_active_pause(self, device: Device) -> SharingPause | None:
        now = timezone.now()
        pause = (
            SharingPause.objects.filter(device=device, ended_at__isnull=True)
            .order_by("-started_at")
            .first()
        )
        if not pause:
            return None
        if pause.expires_at <= now:
            self._expire_pause(pause)
            return None
        return pause

    def sharing_state(self, device: Device) -> dict:
        pause = self.get_active_pause(device)
        if not pause:
            return {
                "paused": False,
                "paused_until": None,
                "resumes_in_s": None,
            }
        now = timezone.now()
        resumes_in = max(0, int((pause.expires_at - now).total_seconds()))
        return {
            "paused": True,
            "paused_until": pause.expires_at,
            "resumes_in_s": resumes_in,
        }

    def covers_timestamp(self, device: Device, event_timestamp) -> bool:
        """True if event_timestamp falls inside any pause window (active or ended)."""
        if event_timestamp is None:
            return False
        pauses = SharingPause.objects.filter(device=device).only(
            "started_at", "expires_at", "ended_at"
        )
        for pause in pauses:
            end = pause.ended_at or pause.expires_at
            if pause.started_at <= event_timestamp < end:
                return True
        return False

    def pause(
        self,
        *,
        user: User,
        device_id,
        duration_minutes: int,
        reason: str = "",
    ) -> SharingPause:
        if duration_minutes not in ALLOWED_PAUSE_MINUTES:
            raise ValidationError(
                "duration_minutes must be one of 15, 30, 60, 120, 240"
            )
        if duration_minutes > MAX_PAUSE_MINUTES:
            raise ValidationError("duration_minutes cannot exceed 24 hours")

        device = self._owned_active_device(user=user, device_id=device_id)
        if self.get_active_pause(device):
            raise ConflictError("Sharing is already paused on this device")

        now = timezone.now()
        with transaction.atomic():
            pause = SharingPause.objects.create(
                tenant=device.tenant,
                device=device,
                started_at=now,
                expires_at=now + timedelta(minutes=duration_minutes),
                created_by=user,
                reason=(reason or "")[:255],
            )

        AuditService().log(
            tenant=device.tenant,
            actor=user,
            action="device.sharing_paused",
            resource_type="device",
            resource_id=device.id,
            metadata={
                "duration_minutes": duration_minutes,
                "paused_until": pause.expires_at.isoformat(),
                "reason": pause.reason,
            },
        )
        # Kick any live screen-share streams for this device.
        from apps.devices.application.services.screen_share_service import (
            ScreenShareService,
        )
        ScreenShareService().terminate_open_for_device(
            device, reason="paused", actor=user
        )
        self._broadcast_status(device)
        return pause

    def resume(self, *, user: User, device_id) -> Device:
        device = self._owned_active_device(user=user, device_id=device_id)
        pause = self.get_active_pause(device)
        if not pause:
            raise ConflictError("Sharing is not currently paused")

        now = timezone.now()
        pause.ended_at = now
        pause.save(update_fields=["ended_at", "updated_at"])

        AuditService().log(
            tenant=device.tenant,
            actor=user,
            action="device.sharing_resumed",
            resource_type="device",
            resource_id=device.id,
            metadata={"ended_at": now.isoformat(), "manual": True},
        )
        self._broadcast_status(device)
        return device

    def _expire_pause(self, pause: SharingPause) -> None:
        if pause.ended_at is not None:
            return
        pause.ended_at = pause.expires_at
        pause.save(update_fields=["ended_at", "updated_at"])
        AuditService().log(
            tenant=pause.tenant,
            actor=None,
            action="device.sharing_pause_expired",
            resource_type="device",
            resource_id=pause.device_id,
            metadata={"paused_until": pause.expires_at.isoformat()},
        )
        # Reload device for broadcast
        device = (
            Device.objects.filter(pk=pause.device_id)
            .select_related("tenant")
            .first()
        )
        if device:
            self._broadcast_status(device)

    def _owned_active_device(self, *, user: User, device_id) -> Device:
        device = (
            Device.objects.filter(pk=device_id, owner=user)
            .select_related("tenant")
            .first()
        )
        if not device:
            raise EntityNotFoundError("Device not found")
        if device.status != Device.Status.ACTIVE:
            raise ValidationError("Only active devices can pause or resume sharing")
        return device

    def _broadcast_status(self, device: Device) -> None:
        """Notify tenant websocket clients. Sync to avoid SQLite lock races in tests."""
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        state = self.sharing_state(device)
        paused_until = state["paused_until"]
        payload = {
            "device_id": str(device.id),
            "status": device.status,
            "sharing": {
                "paused": state["paused"],
                "paused_until": (
                    paused_until.isoformat() if paused_until is not None else None
                ),
                "resumes_in_s": state["resumes_in_s"],
            },
        }
        async_to_sync(channel_layer.group_send)(
            f"tenant_{device.tenant_id}_events",
            {"type": "device.status", "data": payload},
        )
