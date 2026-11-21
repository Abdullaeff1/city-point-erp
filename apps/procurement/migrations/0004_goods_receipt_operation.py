# Generated manually for Phase 4.4.2.3 goods receipt integrity

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("procurement", "0003_m8_stock_procurement"),
        ("warehouse", "0001_scope1_12_domains"),
    ]

    operations = [
        migrations.CreateModel(
            name="GoodsReceiptOperation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operation_key", models.CharField(max_length=64, unique=True)),
                ("mode", models.CharField(choices=[("full", "Full"), ("partial", "Partial")], max_length=16)),
                ("payload_fingerprint", models.CharField(max_length=64)),
                ("lines_json", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="goods_receipt_operations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "po",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="receipt_operations",
                        to="procurement.purchaseorder",
                    ),
                ),
                (
                    "warehouse",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="goods_receipt_operations",
                        to="warehouse.warehouse",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
