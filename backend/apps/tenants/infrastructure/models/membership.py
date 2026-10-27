from django.db import models

from core.infrastructure.models.base import BaseModel


class TenantMembership(BaseModel):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MONITOR = "monitor", "Monitor"
        VIEWER = "viewer", "Viewer"

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="tenant_memberships",
    )
    role = models.CharField(max_length=32, choices=Role.choices, default=Role.VIEWER)

    class Meta:
        db_table = "tenants_membership"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="unique_tenant_user"),
        ]
        indexes = [
            models.Index(fields=["tenant", "role"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.tenant_id} ({self.role})"
