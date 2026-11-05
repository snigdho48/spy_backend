from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("devices", "0007_livemediasession"),
    ]

    operations = [
        migrations.AddField(
            model_name="screensharesession",
            name="control_status",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("requested", "Requested"),
                    ("approved", "Approved"),
                    ("denied", "Denied"),
                ],
                db_index=True,
                default="none",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="screensharesession",
            name="control_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="screensharesession",
            name="control_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="screensharesession",
            name="control_ended_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="screensharesession",
            name="control_ended_reason",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
