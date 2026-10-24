from django.db import migrations, models


def mark_inactive_devices(apps, schema_editor):
    SecurityDevice = apps.get_model("security_portal", "SecurityDevice")
    SecurityDevice.objects.filter(is_active=False).update(status="inactive")


class Migration(migrations.Migration):

    dependencies = [
        ("security_portal", "0002_floor_patrol"),
    ]

    operations = [
        migrations.AddField(
            model_name="securitydevice",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Aktiv"),
                    ("inactive", "Deaktiv"),
                    ("faulty", "Nasaz"),
                ],
                default="active",
                max_length=16,
            ),
        ),
        migrations.RunPython(mark_inactive_devices, migrations.RunPython.noop),
    ]
