from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_totp"),
    ]

    operations = [
        migrations.AddField(
            model_name="refreshtokenrecord",
            name="device_label",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="refreshtokenrecord",
            name="last_used_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
