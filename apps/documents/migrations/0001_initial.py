from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("property", "0001_initial"),
        ("residents", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("file", models.FileField(blank=True, upload_to="documents/%Y/%m/")),
                ("file_type", models.CharField(default="PDF", max_length=16)),
                ("version", models.CharField(blank=True, max_length=32)),
                ("size_label", models.CharField(blank=True, max_length=32)),
                ("published_at", models.DateField()),
                (
                    "company",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.CASCADE,
                        related_name="documents",
                        to="residents.residentcompany",
                    ),
                ),
                (
                    "space",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="documents",
                        to="property.space",
                    ),
                ),
            ],
            options={"ordering": ["-published_at"]},
        ),
    ]
