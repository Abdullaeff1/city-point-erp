import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0001_scope1_12_domains"),
        ("procurement", "0001_scope1_12_domains"),
        ("warehouse", "0002_issue_document"),
    ]

    operations = [
        migrations.AddField(
            model_name="workorder",
            name="resident_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.CreateModel(
            name="WorkOrderCostLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=16)),
                ("source", models.CharField(default="manual", max_length=16)),
                ("description", models.CharField(max_length=255)),
                ("qty", models.DecimalField(decimal_places=3, default=1, max_digits=14)),
                ("unit", models.CharField(default="ədəd", max_length=16)),
                ("unit_price", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                (
                    "po_line",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cost_line",
                        to="procurement.poline",
                    ),
                ),
                (
                    "warehouse_issue_line",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cost_line",
                        to="warehouse.warehouseissueline",
                    ),
                ),
                (
                    "work_order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cost_lines",
                        to="maintenance.workorder",
                    ),
                ),
            ],
            options={"ordering": ["kind", "sort_order", "id"]},
        ),
    ]
