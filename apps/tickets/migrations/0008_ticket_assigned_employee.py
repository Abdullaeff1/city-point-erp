import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0013_access_event_result"),
        ("tickets", "0007_route_technical_cleaning_to_service_desk"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="assigned_employee",
            field=models.ForeignKey(
                blank=True,
                help_text="Service Desk-in təyin etdiyi City Point əməkdaşı",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_service_tickets",
                to="residents.residentemployee",
            ),
        ),
    ]
