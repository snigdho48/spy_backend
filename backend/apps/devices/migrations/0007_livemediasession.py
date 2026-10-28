import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0006_screensharesession"),
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LiveMediaSession",
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
                (
                    "media_kind",
                    models.CharField(
                        choices=[
                            ("camera", "Camera"),
                            ("microphone", "Microphone"),
                            ("both", "Camera + Microphone"),
                        ],
                        db_index=True,
                        default="camera",
                        max_length=16,
                    ),
                ),
                (
                    "camera_facing",
                    models.CharField(blank=True, default="back", max_length=8),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("requested", "Requested"),
                            ("active", "Active"),
                            ("ended", "Ended"),
                            ("denied", "Denied"),
                            ("expired", "Expired"),
                        ],
                        db_index=True,
                        default="requested",
                        max_length=16,
                    ),
                ),
                ("requested_at", models.DateTimeField(db_index=True)),
                (
                    "started_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "ended_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "ended_reason",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "device",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="live_media_sessions",
                        to="devices.device",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="requested_live_media",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)ss",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "devices_live_media_session",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["device", "status"],
                        name="devices_liv_device__f0612b_idx",
                    ),
                    models.Index(
                        fields=["tenant", "-created_at"],
                        name="devices_liv_tenant__6d4de7_idx",
                    ),
                ],
            },
        ),
    ]
