from django.db import models

from core.infrastructure.models.base import BaseModel


class TenantInvite(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        REVOKED = "revoked", "Revoked"
        EXPIRED = "expired", "Expired"

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="invites",
    )
    email = models.EmailField(db_index=True)
    role = models.CharField(
        max_length=32,
        choices=[
            ("admin", "Admin"),
            ("monitor", "Monitor"),
            ("viewer", "Viewer"),
        ],
        default="viewer",
    )
    invited_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_invites",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    expires_at = models.DateTimeField(db_index=True)
    accepted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_invites",
    )
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tenants_invite"
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["email", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "email"],
                condition=models.Q(status="pending"),
                name="unique_pending_invite_per_tenant_email",
            ),
        ]

    def __str__(self) -> str:
        return f"Invite {self.email} → {self.tenant_id} ({self.status})"
