from django.db import migrations


def put_other_last(apps, schema_editor):
    TicketSubcategory = apps.get_model("tickets", "TicketSubcategory")
    TicketSubcategory.objects.filter(name="Digər").update(sort_order=1000)


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0011_other_subcategory_per_category"),
    ]

    operations = [
        migrations.RunPython(put_other_last, migrations.RunPython.noop),
    ]
