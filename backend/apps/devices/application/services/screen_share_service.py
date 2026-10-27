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
from apps.devices.infrastructure.models.screen_share import ScreenShareSession
from apps.tenants.infrastructure.models.membership import TenantMembership
from apps.tenants.infrastructure.models.tenant import Tenant
from core.domain.exceptions import (
    ConflictError,
    ConsentRequiredError,
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)

# The consent scope that gates every part of this feature.
SCREEN_SCOPE = "screen"

# Stale REQUESTED sessions auto-expire after this window (lazy on read).
REQUEST_TTL = timedelta(minutes=15)

MONITOR_ROLES = (
    TenantMembership.Role.OWNER,
    TenantMembership.Role.ADMIN,
    TenantMembership.Role.MONITOR,
)


class ScreenShareService:
    """Consent-gated lifecycle for live screen-share sessions.

    Mirrors the pause/scope/audit patterns already used across the app:
    - an active ``screen`` consent scope is required to request or start,
    - a sharing pause blocks requesting/starting/streaming,
    - every state transition is written to the audit log.
    - REST end / consent revoke / pause kick the live Channels group so
      mid-session revoke cannot keep the WS stream open.
    """

    # ---- consent / pause gates -------------------------------------------

    def _require_screen_consent(self, device: Device) -> None:
        consent = ConsentService().get_active_consent(device)
        if not consent or not consent.has_scope(SCREEN_SCOPE):
            raise ConsentRequiredError(
                "Device has not granted 'screen' consent scope"
            )

    def _require_not_paused(self, device: Device) -> None:
        if SharingPauseService().get_active_pause(device):
            raise ConflictError("Sharing is paused; screen sharing is unavailable")

    # ---- lookups ----------------------------------------------------------

    def _monitor_device(self, *, user: User, tenant: Tenant, device_id) -> Device:
        """Device the signed-in user may monitor in this tenant (role gated)."""
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

    def _owned_active_device(self, *, user: User, device_id) -> Device:
        device = (
            Device.objects.filter(pk=device_id, owner=user)
            .select_related("tenant")
            .first()
        )
        if not device:
            raise EntityNotFoundError("Device not found")
        if device.status != Device.Status.ACTIVE:
            raise ValidationError("Only active devices can share their screen")
        return device

    def get_session_for_user(self, *, user: User, session_id) -> ScreenShareSession:
        """A session the user may see: the monitored owner or a tenant monitor."""
        self.expire_stale_requested()
        session = (
            ScreenShareSession.objects.filter(pk=session_id)
            .select_related("device", "device__tenant", "tenant")
            .first()
        )
        if not session:
            raise EntityNotFoundError("Screen share session not found")
        device = session.device
        if device.owner_id == user.id:
            return session
        membership = TenantMembership.objects.filter(
            user=user, tenant_id=session.tenant_id
        ).first()
        if membership and membership.role in MONITOR_ROLES:
            return session
        raise EntityNotFoundError("Screen share session not found")

    # ---- Channels kick ----------------------------------------------------

    @staticmethod
    def notify_session_closed(session_id, reason: str = "ended") -> None:
        """Broadcast close to the live ``screen_<id>`` group (kicks consumers)."""
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        async_to_sync(channel_layer.group_send)(
            f"screen_{session_id}",
            {"type": "screen.closed", "reason": reason},
        )

    def terminate_open_for_device(
        self,
        device: Device,
        *,
        reason: str,
        actor: User | None = None,
        final_status: str | None = None,
    ) -> int:
        """End every open session for a device and kick its WS group.

        Used when sharing is paused or ``screen`` consent is revoked so a
        mid-session stream cannot continue after the gate flips.
        """
        status = final_status or ScreenShareSession.Status.ENDED
        open_statuses = [
            ScreenShareSession.Status.REQUESTED,
            ScreenShareSession.Status.ACTIVE,
        ]
        sessions = list(
            ScreenShareSession.objects.filter(
                device=device, status__in=open_statuses
            ).select_related("tenant", "device")
        )
        if not sessions:
            return 0

        now = timezone.now()
        for session in sessions:
            session.status = status
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
            action = (
                "screen_share.expired"
                if status == ScreenShareSession.Status.EXPIRED
                else "screen_share.ended"
            )
            self._audit(session, actor, action, {"reason": session.ended_reason})
            self.notify_session_closed(session.id, reason=reason)
        return len(sessions)

    def expire_stale_requested(self, *, device: Device | None = None) -> int:
        """Lazy TTL: REQUESTED rows older than REQUEST_TTL become EXPIRED."""
        cutoff = timezone.now() - REQUEST_TTL
        qs = ScreenShareSession.objects.filter(
            status=ScreenShareSession.Status.REQUESTED,
            requested_at__lt=cutoff,
        )
        if device is not None:
            qs = qs.filter(device=device)
        sessions = list(qs.select_related("tenant", "device"))
        if not sessions:
            return 0
        now = timezone.now()
        for session in sessions:
            session.status = ScreenShareSession.Status.EXPIRED
            session.ended_at = now
            session.ended_reason = "expired"
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
            self._audit(session, None, "screen_share.expired", {"reason": "expired"})
            self.notify_session_closed(session.id, reason="expired")
        return len(sessions)

    # ---- transitions ------------------------------------------------------

    def request_session(
        self, *, user: User, tenant: Tenant, device_id
    ) -> tuple[ScreenShareSession, bool]:
        """Return ``(session, created)``. ``created`` is False when reusing."""
        device = self._monitor_device(user=user, tenant=tenant, device_id=device_id)
        if device.status != Device.Status.ACTIVE:
            raise ValidationError("Device is not active")
        self._require_screen_consent(device)
        self._require_not_paused(device)
        self.expire_stale_requested(device=device)

        # Reuse an already-open session rather than stacking duplicates.
        existing = (
            ScreenShareSession.objects.filter(
                device=device,
                status__in=[
                    ScreenShareSession.Status.REQUESTED,
                    ScreenShareSession.Status.ACTIVE,
                ],
            )
            .order_by("-created_at")
            .first()
        )
        if existing:
            return existing, False

        now = timezone.now()
        with transaction.atomic():
            session = ScreenShareSession.objects.create(
                tenant=device.tenant,
                device=device,
                requested_by=user,
                status=ScreenShareSession.Status.REQUESTED,
                requested_at=now,
            )
        self._audit(session, user, "screen_share.requested")
        return session, True

    def start_session(self, *, user: User, session_id) -> ScreenShareSession:
        """Monitored device owner accepts the request and begins streaming."""
        self.expire_stale_requested()
        session = (
            ScreenShareSession.objects.filter(pk=session_id)
            .select_related("device", "device__tenant", "tenant")
            .first()
        )
        if not session or session.device.owner_id != user.id:
            raise EntityNotFoundError("Screen share session not found")
        if session.status != ScreenShareSession.Status.REQUESTED:
            raise ConflictError("Session is not awaiting start")

        device = session.device
        self._require_screen_consent(device)
        self._require_not_paused(device)

        now = timezone.now()
        session.status = ScreenShareSession.Status.ACTIVE
        session.started_at = now
        session.save(update_fields=["status", "started_at", "updated_at"])
        self._audit(session, user, "screen_share.started")
        return session

    def deny_session(self, *, user: User, session_id, reason: str = "") -> ScreenShareSession:
        """Monitored device owner declines a pending request."""
        session = (
            ScreenShareSession.objects.filter(pk=session_id)
            .select_related("device", "device__tenant", "tenant")
            .first()
        )
        if not session or session.device.owner_id != user.id:
            raise EntityNotFoundError("Screen share session not found")
        if session.status != ScreenShareSession.Status.REQUESTED:
            raise ConflictError("Session is not awaiting start")

        now = timezone.now()
        session.status = ScreenShareSession.Status.DENIED
        session.ended_at = now
        session.ended_reason = (reason or "")[:255]
        session.save(
            update_fields=["status", "ended_at", "ended_reason", "updated_at"]
        )
        self._audit(session, user, "screen_share.denied", {"reason": session.ended_reason})
        self.notify_session_closed(session.id, reason="denied")
        return session

    def end_session(self, *, user: User, session_id, reason: str = "") -> ScreenShareSession:
        """Either side ends an open session."""
        session = self.get_session_for_user(user=user, session_id=session_id)
        if not session.is_open:
            # Idempotent: ending an already-closed session is a no-op.
            return session

        now = timezone.now()
        session.status = ScreenShareSession.Status.ENDED
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
        self._audit(session, user, "screen_share.ended", {"reason": session.ended_reason})
        self.notify_session_closed(session.id, reason=session.ended_reason or "ended")
        return session

    # ---- audit ------------------------------------------------------------

    def _audit(self, session, actor, action, extra=None):
        metadata = {
            "session_id": str(session.id),
            "device_id": str(session.device_id),
            "status": session.status,
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
