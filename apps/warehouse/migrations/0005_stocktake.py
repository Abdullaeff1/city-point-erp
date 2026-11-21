# Generated manually for Product Delivery Phase 8 stocktake.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("warehouse", "0004_m8_stock_procurement"),
    ]

    operations = [
        migrations.CreateModel(
            name="Stocktake",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=32, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Açıq"),
                            ("completed", "Bitirilib"),
                            ("posting", "Düzəlişlər tətbiq olunur"),
                            ("posted", "Düzəlişlər tətbiq olunub"),
                            ("cancelled", "Ləğv"),
                        ],
                        default="open",
                        max_length=16,
                    ),
                ),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                (
                    "completed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stocktakes_completed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "posted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stocktakes_posted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "started_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stocktakes_started",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "warehouse",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="stocktakes",
                        to="warehouse.warehouse",
                    ),
                ),
            ],
            options={"ordering": ["-started_at"]},
        ),
        migrations.CreateModel(
            name="StocktakeLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("unit", models.CharField(default="pcs", max_length=16)),
                ("baseline_qty", models.DecimalField(decimal_places=3, default=0, max_digits=14)),
                ("baseline_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expected_qty", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ("counted_qty", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ("variance_qty", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ("counted_at", models.DateTimeField(blank=True, null=True)),
                ("recount_required", models.BooleanField(default=False)),
                (
                    "activity_after_count",
                    models.BooleanField(
                        default=False,
                        help_text="Balance-affecting movement after counted_at; review before posting.",
                    ),
                ),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "adjustment_movement",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stocktake_lines",
                        to="warehouse.stockmovement",
                    ),
                ),
                (
                    "bin",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stocktake_lines",
                        to="warehouse.bin",
                    ),
                ),
                (
                    "counted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stocktake_lines_counted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "sku",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="stocktake_lines",
                        to="warehouse.sku",
                    ),
                ),
                (
                    "stocktake",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="warehouse.stocktake",
                    ),
                ),
            ],
            options={"ordering": ["sku__code"]},
        ),
        migrations.AlterUniqueTogether(
            name="stocktakeline",
            unique_together={("stocktake", "sku", "bin")},
        ),
    ]
