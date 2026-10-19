from django.db import migrations


def add_technician(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.update_or_create(
        code="technician",
        defaults={"name": "Usta/texniki işçi", "sort_order": 70, "is_active": True},
    )


def remove_technician(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="technician").update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0008_meeting_room_capital"),
    ]

    operations = [
        migrations.RunPython(add_technician, remove_technician),
    ]
