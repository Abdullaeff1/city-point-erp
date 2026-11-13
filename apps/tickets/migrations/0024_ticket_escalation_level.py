from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0023_wo_eligible_all"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="escalated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="escalation_level",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
