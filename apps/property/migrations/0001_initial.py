from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("residents", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="Building",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(default="City Point Business Center", max_length=120)),
                ("code", models.CharField(default="CP", max_length=32, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name="Contractor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=160)),
                ("contact_email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=64)),
            ],
        ),
        migrations.CreateModel(
            name="Floor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=16)),
                ("name", models.CharField(max_length=64)),
                ("building", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="floors", to="property.building")),
            ],
            options={"unique_together": {("building", "code")}},
        ),
        migrations.CreateModel(
            name="Space",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(blank=True, max_length=120)),
                ("area_m2", models.DecimalField(decimal_places=1, default=0, max_digits=10)),
                ("access_zone", models.CharField(blank=True, max_length=32)),
                (
                    "occupancy",
                    models.CharField(
                        choices=[
                            ("active_lease", "Aktiv icarə dövrü"),
                            ("vacant", "Boş"),
                            ("maintenance", "Texniki xidmət"),
                        ],
                        default="active_lease",
                        max_length=32,
                    ),
                ),
                ("cost_center", models.CharField(blank=True, max_length=64)),
                ("plan_revision", models.CharField(blank=True, max_length=32)),
                ("floor", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="spaces", to="property.floor")),
                (
                    "resident",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="spaces",
                        to="residents.residentcompany",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Asset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=160)),
                ("asset_code", models.CharField(blank=True, max_length=64)),
                ("space", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="assets", to="property.space")),
            ],
        ),
    ]
