from django.db import migrations


def add_interview(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.update_or_create(
        code="interview",
        defaults={"name": "Müsahibə", "sort_order": 100, "is_active": True},
    )


def remove_interview(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="interview").update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0012_new_employee_visit_type"),
    ]

    operations = [
        migrations.RunPython(add_interview, remove_interview),
    ]
