from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0012_phases_3_13_foundations"),
    ]

    operations = [
        migrations.AddField(
            model_name="accessevent",
            name="result",
            field=models.CharField(
                choices=[("granted", "Uğurlu"), ("denied", "Uğursuz")],
                db_index=True,
                default="granted",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="accessevent",
            name="employee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="access_events",
                to="residents.residentemployee",
            ),
        ),
    ]
