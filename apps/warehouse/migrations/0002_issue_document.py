import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("maintenance", "0001_scope1_12_domains"),
        ("warehouse", "0001_scope1_12_domains"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WarehouseIssue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=32, unique=True)),
                ("status", models.CharField(default="open", max_length=16)),
                ("issued_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                (
                    "issued_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="warehouse_issues_confirmed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="warehouse_issue_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "warehouse",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="issues",
                        to="warehouse.warehouse",
                    ),
                ),
                (
                    "work_order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="warehouse_issues",
                        to="maintenance.workorder",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="WarehouseIssueLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("requested_qty", models.DecimalField(decimal_places=3, max_digits=14)),
                ("issued_qty", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ("unit_cost", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                (
                    "issue",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="warehouse.warehouseissue",
                    ),
                ),
                (
                    "sku",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="issue_lines",
                        to="warehouse.sku",
                    ),
                ),
            ],
        ),
    ]
