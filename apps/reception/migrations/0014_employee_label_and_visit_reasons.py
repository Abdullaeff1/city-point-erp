from django.db import migrations


def update_reasons(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="new-employee").update(name="Əməkdaş", is_active=True)
    VisitorType.objects.update_or_create(
        code="kassa",
        defaults={"name": "Kassa", "sort_order": 110, "is_active": True},
    )
    VisitorType.objects.update_or_create(
        code="document-related",
        defaults={"name": "Sənəd ilə bağlı", "sort_order": 120, "is_active": True},
    )


def revert_reasons(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    VisitorType.objects.filter(code="new-employee").update(name="Yeni Əməkdaş")
    VisitorType.objects.filter(code__in=["kassa", "document-related"]).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0013_interview_visit_type"),
    ]

    operations = [
        migrations.RunPython(update_reasons, revert_reasons),
    ]
