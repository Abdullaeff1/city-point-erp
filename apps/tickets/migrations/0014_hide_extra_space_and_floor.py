from django.db import migrations


def hide_commercial_subs(apps, schema_editor):
    TicketSubcategory = apps.get_model("tickets", "TicketSubcategory")
    TicketSubcategory.objects.filter(
        category__slug="commercial-space",
        slug__in=("additional-office", "different-floor"),
    ).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0013_security_cargo_and_event"),
    ]

    operations = [
        migrations.RunPython(hide_commercial_subs, migrations.RunPython.noop),
    ]
