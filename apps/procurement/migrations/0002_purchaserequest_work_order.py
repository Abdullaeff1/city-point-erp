import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0001_scope1_12_domains"),
        ("procurement", "0001_scope1_12_domains"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaserequest",
            name="work_order",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="purchase_requests",
                to="maintenance.workorder",
            ),
        ),
    ]
