from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0015_intern_visit_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="guestvisit",
            name="actual_departure_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="guestvisit",
            name="check_out_recorded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
