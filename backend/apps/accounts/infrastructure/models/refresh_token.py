from django.db import models

from core.infrastructure.models.base import BaseModel


class RefreshTokenRecord(BaseModel):
    """Tracks issued refresh tokens for rotation and revocation."""

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
    )
    jti = models.CharField(max_length=255, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    replaced_by_jti = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)

    class Meta:
        db_table = "accounts_refresh_token"
        indexes = [
            models.Index(fields=["user", "revoked_at"]),
        ]

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def __str__(self) -> str:
        state = "revoked" if self.revoked_at else "active"
        return f"Refresh token {self.pk} ({state})"
