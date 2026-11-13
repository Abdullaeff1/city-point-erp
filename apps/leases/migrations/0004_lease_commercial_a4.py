from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("leases", "0003_lease_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="lease",
            name="rent_rate_per_m2",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="lease",
            name="service_rate_per_m2",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="lease",
            name="deposit_months",
            field=models.PositiveSmallIntegerField(default=2),
        ),
        migrations.AddField(
            model_name="lease",
            name="parking_included_free",
            field=models.BooleanField(
                default=True,
                help_text="Parkinq icarə dəyərinə daxil deyil; ödənişsiz ayrılır",
            ),
        ),
        migrations.AddField(
            model_name="lease",
            name="parking_notes",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="lease",
            name="fit_out_notes",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.CreateModel(
            name="LeaseAddon",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(blank=True, max_length=32)),
                ("label", models.CharField(max_length=120)),
                ("rate_per_m2", models.DecimalField(decimal_places=4, default=0, max_digits=12)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "lease",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="addons",
                        to="leases.lease",
                    ),
                ),
            ],
            options={"ordering": ["id"]},
        ),
        migrations.CreateModel(
            name="DepositSettlement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("full_return", "Tam qaytarma"),
                            ("partial_return", "Qismən qaytarma"),
                            ("withhold", "Tutma"),
                        ],
                        default="full_return",
                        max_length=24,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("withhold_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("reason", models.CharField(blank=True, max_length=255)),
                ("settled_at", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "lease",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deposit_settlements",
                        to="leases.lease",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
