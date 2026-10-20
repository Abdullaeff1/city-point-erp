from django.db import migrations


def add_new_employee(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.update_or_create(
        code="new-employee",
        defaults={"name": "Yeni Əməkdaş", "sort_order": 90, "is_active": True},
    )


def remove_new_employee(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="new-employee").update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0011_patient_visit_type"),
    ]

    operations = [
        migrations.RunPython(add_new_employee, remove_new_employee),
    ]
