from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("property", "0001_initial"),
        ("residents", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="Guest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("full_name", models.CharField(max_length=160)),
            ],
        ),
        migrations.CreateModel(
            name="GuestVisit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("location_note", models.CharField(blank=True, max_length=120)),
                (
                    "status",
                    models.CharField(
                        choices=[("waiting", "Gözləyir"), ("inside", "İçəridə"), ("left", "Çıxış")],
                        default="waiting",
                        max_length=16,
                    ),
                ),
                ("scheduled_for", models.DateField()),
                ("check_in_at", models.DateTimeField(blank=True, null=True)),
                ("check_out_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="guest_visits", to="residents.residentcompany"),
                ),
                (
                    "floor",
                    models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to="property.floor"),
                ),
                (
                    "guest",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="visits", to="reception.guest"),
                ),
                (
                    "host",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="hosted_visits",
                        to="residents.residentemployee",
                    ),
                ),
                (
                    "space",
                    models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to="property.space"),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
