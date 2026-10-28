"""Refresh-token session tracking and revocation."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from apps.accounts.infrastructure.models.refresh_token import RefreshTokenRecord
from apps.accounts.infrastructure.models.user import User
from core.domain.exceptions import EntityNotFoundError, PermissionDeniedError


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, dt_timezone.utc)
    return dt


class SessionService:
    def record_login(
        self,
        *,
        user: User,
        refresh: RefreshToken,
        ip_address: str | None = None,
        user_agent: str = "",
        device_label: str = "",
    ) -> RefreshTokenRecord:
        jti = str(refresh.get("jti", ""))
        exp = refresh.get("exp")
        expires_at = (
            datetime.fromtimestamp(exp, tz=dt_timezone.utc) if exp else timezone.now()
        )
        record, _ = RefreshTokenRecord.objects.update_or_create(
            jti=jti,
            defaults={
                "user": user,
                "expires_at": expires_at,
                "revoked_at": None,
                "replaced_by_jti": "",
                "ip_address": ip_address or None,
                "user_agent": (user_agent or "")[:512],
                "device_label": (device_label or "")[:128],
                "last_used_at": timezone.now(),
            },
        )
        return record

    def touch_refresh(
        self,
        *,
        old_jti: str,
        new_refresh: RefreshToken,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> None:
        """Mark prior session rotated and upsert the replacement."""
        now = timezone.now()
        old = RefreshTokenRecord.objects.filter(jti=old_jti).first()
        new_jti = str(new_refresh.get("jti", ""))
        exp = new_refresh.get("exp")
        expires_at = (
            datetime.fromtimestamp(exp, tz=dt_timezone.utc) if exp else now
        )
        if old:
            old.revoked_at = now
            old.replaced_by_jti = new_jti
            old.save(update_fields=["revoked_at", "replaced_by_jti", "updated_at"])
            user = old.user
            device_label = old.device_label
            ua = user_agent or old.user_agent
            ip = ip_address or old.ip_address
        else:
            # Fallback: resolve user from the new token claim.
            user_id = new_refresh.get("user_id")
            user = User.objects.filter(pk=user_id).first()
            if not user:
                return
            device_label = ""
            ua = user_agent or ""
            ip = ip_address

        RefreshTokenRecord.objects.update_or_create(
            jti=new_jti,
            defaults={
                "user": user,
                "expires_at": expires_at,
                "revoked_at": None,
                "replaced_by_jti": "",
                "ip_address": ip,
                "user_agent": (ua or "")[:512],
                "device_label": (device_label or "")[:128],
                "last_used_at": now,
            },
        )

    def list_sessions(self, *, user: User, current_jti: str | None = None) -> list[dict]:
        now = timezone.now()
        rows = (
            RefreshTokenRecord.objects.filter(user=user, revoked_at__isnull=True)
            .filter(expires_at__gt=now)
            .order_by("-last_used_at", "-created_at")
        )
        out = []
        for r in rows:
            out.append(
                {
                    "id": str(r.id),
                    "device_label": r.device_label or self._label_from_ua(r.user_agent),
                    "user_agent": r.user_agent,
                    "ip_address": r.ip_address,
                    "created_at": r.created_at.isoformat(),
                    "last_used_at": r.last_used_at.isoformat()
                    if r.last_used_at
                    else r.created_at.isoformat(),
                    "is_current": bool(current_jti and r.jti == current_jti),
                }
            )
        return out

    @staticmethod
    def _label_from_ua(ua: str) -> str:
        ua = ua or ""
        lower = ua.lower()
        if "android" in lower:
            return "Android device"
        if "iphone" in lower or "ios" in lower:
            return "iOS device"
        if "windows" in lower:
            return "Windows"
        if "mac" in lower:
            return "Mac"
        if "linux" in lower:
            return "Linux"
        return "Unknown device"

    def revoke(self, *, user: User, session_id) -> None:
        record = RefreshTokenRecord.objects.filter(pk=session_id, user=user).first()
        if not record:
            raise EntityNotFoundError("Session not found")
        self._revoke_record(record)

    def revoke_others(self, *, user: User, current_jti: str | None) -> int:
        qs = RefreshTokenRecord.objects.filter(user=user, revoked_at__isnull=True)
        if current_jti:
            qs = qs.exclude(jti=current_jti)
        count = 0
        for record in qs:
            self._revoke_record(record)
            count += 1
        return count

    def revoke_by_refresh_token(self, *, refresh_token: str) -> None:
        try:
            token = RefreshToken(refresh_token)
        except TokenError:
            return
        jti = str(token.get("jti", ""))
        record = RefreshTokenRecord.objects.filter(jti=jti).first()
        if record:
            self._revoke_record(record)
        else:
            try:
                token.blacklist()
            except Exception:
                pass

    def _revoke_record(self, record: RefreshTokenRecord) -> None:
        if record.revoked_at:
            return
        record.revoked_at = timezone.now()
        record.save(update_fields=["revoked_at", "updated_at"])
        # Blacklist matching outstanding JWT if present.
        outstanding = OutstandingToken.objects.filter(jti=record.jti).first()
        if outstanding:
            BlacklistedToken.objects.get_or_create(token=outstanding)

    def jti_from_refresh(self, refresh_token: str | None) -> str | None:
        if not refresh_token:
            return None
        try:
            return str(RefreshToken(refresh_token).get("jti", "")) or None
        except TokenError:
            return None
