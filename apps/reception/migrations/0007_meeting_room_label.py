from django.db import migrations


def rename_meeting(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="meeting").update(name="Meeting room", is_active=True)


def restore_meeting(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="meeting").update(name="İclas üçün")


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0006_visit_reason_types"),
    ]

    operations = [
        migrations.RunPython(rename_meeting, restore_meeting),
    ]
