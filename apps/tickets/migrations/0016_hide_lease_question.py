from django.db import migrations


def hide_lease_question(apps, schema_editor):
    TicketSubcategory = apps.get_model("tickets", "TicketSubcategory")
    TicketSubcategory.objects.filter(category__slug="lease", slug="lease-question").update(
        is_active=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0015_lease_matter_and_agreement"),
    ]

    operations = [
        migrations.RunPython(hide_lease_question, migrations.RunPython.noop),
    ]
