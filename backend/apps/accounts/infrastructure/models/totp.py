"""TOTP recovery codes (hashed, single-use)."""

from django.db import models

from core.infrastructure.models.base import BaseModel


class TotpRecoveryCode(BaseModel):
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="totp_recovery_codes",
    )
    code_hash = models.CharField(max_length=64, db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_totp_recovery_code"
        indexes = [
            models.Index(fields=["user", "used_at"]),
        ]

    @property
    def is_used(self) -> bool:
        return self.used_at is not None
