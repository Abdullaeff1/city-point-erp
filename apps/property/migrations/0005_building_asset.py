from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("property", "0004_phases_3_13_foundations"),
    ]

    operations = [
        migrations.CreateModel(
            name="BuildingAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("code", models.CharField(blank=True, max_length=64)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("hvac", "HVAC"),
                            ("lift", "Lift"),
                            ("electric", "Elektrik"),
                            ("fire", "Yanğın"),
                            ("pump", "Nasos"),
                            ("furniture", "Mebel"),
                            ("other", "Digər"),
                        ],
                        default="other",
                        max_length=24,
                    ),
                ),
                ("location", models.CharField(blank=True, max_length=160)),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("last_inspected_on", models.DateField(blank=True, null=True)),
                ("next_inspection_on", models.DateField(blank=True, null=True)),
                (
                    "floor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="building_assets",
                        to="property.floor",
                    ),
                ),
            ],
            options={
                "ordering": ["category", "name"],
            },
        ),
    ]
