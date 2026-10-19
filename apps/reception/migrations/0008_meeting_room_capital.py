from django.db import migrations


def capitalize_meeting(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="meeting").update(name="Meeting room")


def lowercase_meeting(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="meeting").update(name="meeting room")


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0007_meeting_room_label"),
    ]

    operations = [
        migrations.RunPython(capitalize_meeting, lowercase_meeting),
    ]
