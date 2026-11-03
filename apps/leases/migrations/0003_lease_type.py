from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leases", "0002_phases_3_13_foundations"),
    ]

    operations = [
        migrations.AddField(
            model_name="lease",
            name="lease_type",
            field=models.CharField(
                blank=True,
                help_text="Məs. ofis, anbar, qarışıq",
                max_length=64,
                verbose_name="İcarə növü",
            ),
        ),
    ]
