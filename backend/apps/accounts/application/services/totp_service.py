"""TOTP enrollment, verification, recovery codes, and pre-auth tokens."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

import pyotp
from django.core import signing
from django.utils import timezone

from apps.accounts.application.services.token_service import build_auth_payload
from apps.accounts.infrastructure.models.totp import TotpRecoveryCode
from apps.accounts.infrastructure.models.user import User
from core.crypto.field_encryption import decrypt_str, encrypt_str
from core.domain.exceptions import PermissionDeniedError, ValidationError

ISSUER = "Spy Love"
PRE_AUTH_LIFETIME = timedelta(minutes=5)
RECOVERY_CODE_COUNT = 8


def _hash_code(raw: str) -> str:
    return hashlib.sha256(raw.strip().upper().encode("utf-8")).hexdigest()


class TotpService:
    def status(self, user: User) -> dict:
        return {
            "enabled": bool(user.totp_enabled),
            "confirmed_at": user.totp_confirmed_at.isoformat()
            if user.totp_confirmed_at
            else None,
            "recovery_codes_remaining": TotpRecoveryCode.objects.filter(
                user=user, used_at__isnull=True
            ).count()
            if user.totp_enabled
            else 0,
        }

    def enroll(self, user: User) -> dict:
        if user.totp_enabled:
            raise ValidationError("Two-factor authentication is already enabled")
        secret = pyotp.random_base32()
        user.totp_secret_encrypted = encrypt_str(secret)
        user.totp_enabled = False
        user.totp_confirmed_at = None
        user.save(
            update_fields=[
                "totp_secret_encrypted",
                "totp_enabled",
                "totp_confirmed_at",
                "updated_at",
            ]
        )
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=user.email, issuer_name=ISSUER)
        return {"secret": secret, "otpauth_uri": uri}

    def _plain_secret(self, user: User) -> str:
        if not user.totp_secret_encrypted:
            raise ValidationError("No pending TOTP enrollment")
        return decrypt_str(user.totp_secret_encrypted)

    def verify_and_enable(self, user: User, code: str) -> dict:
        if user.totp_enabled:
            raise ValidationError("Two-factor authentication is already enabled")
        secret = self._plain_secret(user)
        if not pyotp.TOTP(secret).verify(code.strip(), valid_window=1):
            raise ValidationError("Invalid authentication code")
        user.totp_enabled = True
        user.totp_confirmed_at = timezone.now()
        user.save(update_fields=["totp_enabled", "totp_confirmed_at", "updated_at"])
        codes = self._rotate_recovery_codes(user)
        return {"enabled": True, "recovery_codes": codes}

    def _rotate_recovery_codes(self, user: User) -> list[str]:
        TotpRecoveryCode.objects.filter(user=user).delete()
        raw_codes: list[str] = []
        for _ in range(RECOVERY_CODE_COUNT):
            raw = "-".join(
                secrets.token_hex(2).upper() for _ in range(2)
            )  # e.g. A1B2-C3D4
            TotpRecoveryCode.objects.create(user=user, code_hash=_hash_code(raw))
            raw_codes.append(raw)
        return raw_codes

    def regenerate_recovery_codes(self, user: User, *, code: str | None = None, password: str | None = None) -> list[str]:
        self._assert_enabled(user)
        self._assert_password_or_code(user, password=password, code=code)
        return self._rotate_recovery_codes(user)

    def disable(self, user: User, *, password: str | None = None, code: str | None = None) -> None:
        self._assert_enabled(user)
        self._assert_password_or_code(user, password=password, code=code)
        user.totp_enabled = False
        user.totp_secret_encrypted = ""
        user.totp_confirmed_at = None
        user.save(
            update_fields=[
                "totp_enabled",
                "totp_secret_encrypted",
                "totp_confirmed_at",
                "updated_at",
            ]
        )
        TotpRecoveryCode.objects.filter(user=user).delete()

    def _assert_enabled(self, user: User) -> None:
        if not user.totp_enabled:
            raise ValidationError("Two-factor authentication is not enabled")

    def _assert_password_or_code(
        self, user: User, *, password: str | None, code: str | None
    ) -> None:
        if password:
            if not user.has_usable_password() or not user.check_password(password):
                raise PermissionDeniedError("Invalid password")
            return
        if code:
            if not self.verify_code_or_recovery(user, code):
                raise PermissionDeniedError("Invalid authentication code")
            return
        raise ValidationError("Password or authentication code is required")

    def verify_code_or_recovery(self, user: User, code: str) -> bool:
        secret = self._plain_secret(user)
        if pyotp.TOTP(secret).verify(code.strip(), valid_window=1):
            return True
        return self._consume_recovery_code(user, code)

    def _consume_recovery_code(self, user: User, raw: str) -> bool:
        code_hash = _hash_code(raw)
        row = (
            TotpRecoveryCode.objects.filter(
                user=user, code_hash=code_hash, used_at__isnull=True
            )
            .order_by("created_at")
            .first()
        )
        if not row:
            return False
        row.used_at = timezone.now()
        row.save(update_fields=["used_at", "updated_at"])
        return True

    def issue_pre_auth_token(self, user: User) -> str:
        return signing.dumps(
            {"uid": str(user.id), "purpose": "pre_auth_2fa"},
            salt="totp-pre-auth",
        )

    def user_from_pre_auth(self, raw: str) -> User:
        try:
            data = signing.loads(
                raw,
                salt="totp-pre-auth",
                max_age=int(PRE_AUTH_LIFETIME.total_seconds()),
            )
        except signing.BadSignature as exc:
            raise PermissionDeniedError("Invalid or expired pre-auth token") from exc
        if data.get("purpose") != "pre_auth_2fa":
            raise PermissionDeniedError("Invalid pre-auth token")
        user = User.objects.filter(pk=data.get("uid"), is_active=True).first()
        if not user or not user.totp_enabled:
            raise PermissionDeniedError("Invalid pre-auth token")
        return user

    def complete_login(self, *, pre_auth_token: str, code: str) -> dict:
        user = self.user_from_pre_auth(pre_auth_token)
        if not self.verify_code_or_recovery(user, code):
            raise PermissionDeniedError("Invalid authentication code")
        return build_auth_payload(user)
