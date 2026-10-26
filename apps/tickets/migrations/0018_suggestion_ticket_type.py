from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0017_billing_rent_services_deposit"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticket",
            name="ticket_type",
            field=models.CharField(
                choices=[
                    ("incident", "Hadisə"),
                    ("service_request", "Xidmət sorğusu"),
                    ("complaint", "Şikayət"),
                    ("commercial", "Kommersiya sorğusu"),
                    ("suggestion", "Təklif"),
                ],
                default="incident",
                max_length=32,
            ),
        ),
    ]
