from __future__ import annotations

from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from apps.accounts.infrastructure.models.user import User
from apps.audit.application.services.audit_service import AuditService
from apps.devices.application.services.pairing_service import ConsentService
from apps.devices.application.services.sharing_pause_service import SharingPauseService
from apps.devices.infrastructure.models.device import Device
from apps.devices.infrastructure.models.live_media import LiveMediaSession
from apps.tenants.infrastructure.models.membership import TenantMembership
from apps.tenants.infrastructure.models.tenant import Tenant
from core.domain.exceptions import (
    ConflictError,
    ConsentRequiredError,
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)

REQUEST_TTL = timedelta(minutes=15)

MONITOR_ROLES = (
    TenantMembership.Role.OWNER,
    TenantMembership.Role.ADMIN,
    TenantMembership.Role.MONITOR,
)

SCOPE_FOR_KIND = {
    LiveMediaSession.MediaKind.CAMERA: frozenset({"camera"}),
    LiveMediaSession.MediaKind.MICROPHONE: frozenset({"microphone"}),
    LiveMediaSession.MediaKind.BOTH: frozenset({"camera", "microphone"}),
}


class LiveMediaService:
    """Consent-gated live camera / microphone sessions (enrollment scopes)."""

    def _require_scopes(self, device: Device, scopes: set[str]) -> None:
        consent = ConsentService().get_active_consent(device)
        if not consent:
            raise ConsentRequiredError("Device has no active consent")
        missing = scopes - set(consent.scopes or [])
        if missing:
            raise ConsentRequiredError(
                f"Device has not granted scope(s): {', '.join(sorted(missing))}"
            )

    def _require_not_paused(self, device: Device) -> None:
        if SharingPauseService().get_active_pause(device):
            raise ConflictError("Sharing is paused; live media is unavailable")

    def _monitor_device(self, *, user: User, tenant: Tenant, device_id) -> Device:
        device = (
            Device.objects.filter(tenant=tenant, pk=device_id)
            .select_related("tenant")
            .first()
        )
        if not device:
            raise EntityNotFoundError("Device not found")
        membership = TenantMembership.objects.filter(user=user, tenant=tenant).first()
        if not membership or membership.role not in MONITOR_ROLES:
            raise PermissionDeniedError(
                "Insufficient permissions to monitor this device"
            )
        return device

    def get_session_for_user(self, *, user: User, session_id) -> LiveMediaSession:
        self.expire_stale_requested()
        session = (
            LiveMediaSession.objects.filter(pk=session_id)
            .select_related("device", "device__tenant", "tenant")
            .first()
        )
        if not session:
            raise EntityNotFoundError("Live media session not found")
        if session.device.owner_id == user.id:
            return session
        membership = TenantMembership.objects.filter(
            user=user, tenant_id=session.tenant_id
        ).first()
        if membership and membership.role in MONITOR_ROLES:
            return session
        raise EntityNotFoundError("Live media session not found")

    @staticmethod
    def notify_session_closed(session_id, reason: str = "ended") -> None:
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        async_to_sync(channel_layer.group_send)(
            f"media_{session_id}",
            {"type": "media.closed", "reason": reason},
        )

    def close_open_sessions_for_device(self, device: Device, reason: str = "revoked") -> int:
        sessions = list(
            LiveMediaSession.objects.filter(
                device=device,
                status__in=[
                    LiveMediaSession.Status.REQUESTED,
                    LiveMediaSession.Status.ACTIVE,
                ],
            )
        )
        now = timezone.now()
        for session in sessions:
            session.status = LiveMediaSession.Status.ENDED
            session.ended_at = now
            session.ended_reason = reason[:255]
            if session.started_at is None:
                session.started_at = session.requested_at
            session.save(
                update_fields=[
                    "status",
                    "ended_at",
                    "ended_reason",
                    "started_at",
                    "updated_at",
                ]
            )
            self.notify_session_closed(session.id, reason=reason)
        return len(sessions)

    def expire_stale_requested(self, device: Device | None = None) -> int:
        cutoff = timezone.now() - REQUEST_TTL
        qs = LiveMediaSession.objects.filter(
            status=LiveMediaSession.Status.REQUESTED,
            requested_at__lt=cutoff,
        )
        if device is not None:
            qs = qs.filter(device=device)
        sessions = list(qs)
        now = timezone.now()
        for session in sessions:
            session.status = LiveMediaSession.Status.EXPIRED
            session.ended_at = now
            session.ended_reason = "expired"
            session.save(
                update_fields=["status", "ended_at", "ended_reason", "updated_at"]
            )
            self._audit(session, None, "live_media.expired", {"reason": "expired"})
            self.notify_session_closed(session.id, reason="expired")
        return len(sessions)

    def request_session(
        self,
        *,
        user: User,
        tenant: Tenant,
        device_id,
        media_kind: str = "camera",
        camera_facing: str = "back",
    ) -> tuple[LiveMediaSession, bool]:
        if media_kind not in LiveMediaSession.MediaKind.values:
            raise ValidationError("Invalid media_kind")
        facing = "front" if camera_facing == "front" else "back"
        device = self._monitor_device(user=user, tenant=tenant, device_id=device_id)
        if device.status != Device.Status.ACTIVE:
            raise ValidationError("Device is not active")
        scopes = set(SCOPE_FOR_KIND[media_kind])
        self._require_scopes(device, scopes)
        self._require_not_paused(device)
        self.expire_stale_requested(device=device)

        existing = (
            LiveMediaSession.objects.filter(
                device=device,
                media_kind=media_kind,
                status__in=[
                    LiveMediaSession.Status.REQUESTED,
                    LiveMediaSession.Status.ACTIVE,
                ],
            )
            .order_by("-created_at")
            .first()
        )
        if existing:
            if existing.camera_facing != facing and media_kind != LiveMediaSession.MediaKind.MICROPHONE:
                existing.camera_facing = facing
                existing.save(update_fields=["camera_facing", "updated_at"])
            return existing, False

        # Enrollment scopes already gate access — no per-session approval.
        # Session opens as ACTIVE so the monitored device can start capture
        # silently without a "requested → accept" handshake.
        now = timezone.now()
        with transaction.atomic():
            session = LiveMediaSession.objects.create(
                tenant=device.tenant,
                device=device,
                requested_by=user,
                media_kind=media_kind,
                camera_facing=facing,
                status=LiveMediaSession.Status.ACTIVE,
                requested_at=now,
                started_at=now,
            )
        self._audit(
            session,
            user,
            "live_media.requested",
            {"media_kind": media_kind, "camera_facing": facing, "auto_active": True},
        )
        self._audit(session, user, "live_media.started", {"auto_active": True})
        return session, True

    def start_session(self, *, user: User, session_id) -> LiveMediaSession:
        """Publisher claim / idempotent confirm. Sessions open as ACTIVE on request."""
        self.expire_stale_requested()
        session = (
            LiveMediaSession.objects.filter(pk=session_id)
            .select_related("device", "device__tenant", "tenant")
            .first()
        )
        if not session or session.device.owner_id != user.id:
            raise EntityNotFoundError("Live media session not found")
        if session.status == LiveMediaSession.Status.ACTIVE:
            # Already auto-activated at request time — re-check scopes and return.
            device = session.device
            self._require_scopes(device, set(SCOPE_FOR_KIND[session.media_kind]))
            self._require_not_paused(device)
            return session
        if session.status != LiveMediaSession.Status.REQUESTED:
            raise ConflictError("Session is not awaiting start")

        device = session.device
        self._require_scopes(device, set(SCOPE_FOR_KIND[session.media_kind]))
        self._require_not_paused(device)

        now = timezone.now()
        session.status = LiveMediaSession.Status.ACTIVE
        session.started_at = now
        session.save(update_fields=["status", "started_at", "updated_at"])
        self._audit(session, user, "live_media.started")
        return session

    def update_facing(self, *, user: User, session_id, facing: str) -> LiveMediaSession:
        session = self.get_session_for_user(user=user, session_id=session_id)
        if not session.is_open:
            raise ConflictError("Session is closed")
        if session.media_kind == LiveMediaSession.MediaKind.MICROPHONE:
            raise ValidationError("Microphone sessions have no camera facing")
        session.camera_facing = "front" if facing == "front" else "back"
        session.save(update_fields=["camera_facing", "updated_at"])
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"media_{session.id}",
                {
                    "type": "media.relay",
                    "payload": {
                        "type": "media.signal",
                        "session_id": str(session.id),
                        "data": {"signal": "switch_camera", "facing": session.camera_facing},
                    },
                    "sender": None,
                },
            )
        return session

    def end_session(self, *, user: User, session_id, reason: str = "") -> LiveMediaSession:
        session = self.get_session_for_user(user=user, session_id=session_id)
        if not session.is_open:
            return session
        now = timezone.now()
        session.status = LiveMediaSession.Status.ENDED
        session.ended_at = now
        session.ended_reason = (reason or "")[:255]
        if session.started_at is None:
            session.started_at = session.requested_at
        session.save(
            update_fields=[
                "status",
                "ended_at",
                "ended_reason",
                "started_at",
                "updated_at",
            ]
        )
        self._audit(session, user, "live_media.ended", {"reason": session.ended_reason})
        self.notify_session_closed(session.id, reason=session.ended_reason or "ended")
        return session

    def _audit(self, session, actor, action, extra=None):
        metadata = {
            "session_id": str(session.id),
            "device_id": str(session.device_id),
            "status": session.status,
            "media_kind": session.media_kind,
        }
        if extra:
            metadata.update(extra)
        AuditService().log(
            tenant=session.tenant,
            actor=actor,
            action=action,
            resource_type="device",
            resource_id=session.device_id,
            metadata=metadata,
        )
