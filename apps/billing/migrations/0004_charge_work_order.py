import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0003_phases_3_13_foundations"),
        ("maintenance", "0001_scope1_12_domains"),
    ]

    operations = [
        migrations.AddField(
            model_name="charge",
            name="work_order",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="charges",
                to="maintenance.workorder",
            ),
        ),
    ]
