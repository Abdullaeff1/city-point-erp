from django.db import migrations


def hide_access_fault(apps, schema_editor):
    TicketSubcategory = apps.get_model("tickets", "TicketSubcategory")
    TicketSubcategory.objects.filter(category__slug="security", slug="access-fault").update(
        is_active=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0019_security_card_related"),
    ]

    operations = [
        migrations.RunPython(hide_access_fault, migrations.RunPython.noop),
    ]
