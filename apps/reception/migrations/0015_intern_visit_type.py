from django.db import migrations


def add_intern(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.update_or_create(
        code="intern",
        defaults={"name": "Təcrübəçi", "sort_order": 95, "is_active": True},
    )


def remove_intern(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="intern").update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0014_employee_label_and_visit_reasons"),
    ]

    operations = [
        migrations.RunPython(add_intern, remove_intern),
    ]
