from django.db import migrations


def add_patient(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.update_or_create(
        code="patient",
        defaults={"name": "Pasiyent", "sort_order": 80, "is_active": True},
    )


def remove_patient(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="patient").update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0010_guest_list_import"),
    ]

    operations = [
        migrations.RunPython(add_patient, remove_patient),
    ]
