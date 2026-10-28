import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantInvite",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("email", models.EmailField(db_index=True, max_length=254)),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("admin", "Admin"),
                            ("monitor", "Monitor"),
                            ("viewer", "Viewer"),
                        ],
                        default="viewer",
                        max_length=32,
                    ),
                ),
                ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("accepted", "Accepted"),
                            ("declined", "Declined"),
                            ("revoked", "Revoked"),
                            ("expired", "Expired"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                (
                    "accepted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="accepted_invites",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "invited_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sent_invites",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invites",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "tenants_invite",
            },
        ),
        migrations.AddIndex(
            model_name="tenantinvite",
            index=models.Index(fields=["tenant", "status"], name="tenants_inv_tenant__7e2d1a_idx"),
        ),
        migrations.AddIndex(
            model_name="tenantinvite",
            index=models.Index(fields=["email", "status"], name="tenants_inv_email_8c3b2f_idx"),
        ),
        migrations.AddConstraint(
            model_name="tenantinvite",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "pending")),
                fields=("tenant", "email"),
                name="unique_pending_invite_per_tenant_email",
            ),
        ),
    ]
