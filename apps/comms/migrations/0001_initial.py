from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="Announcement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("title", models.CharField(max_length=200)),
                ("body", models.TextField()),
                (
                    "severity",
                    models.CharField(
                        choices=[("info", "Info"), ("important", "Vacib"), ("update", "Yenilənmə")],
                        default="info",
                        max_length=16,
                    ),
                ),
                ("published_at", models.DateField()),
            ],
            options={"ordering": ["-published_at"]},
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("message", models.CharField(max_length=255)),
                ("is_read", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("ticket", models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, related_name="notifications", to="tickets.ticket")),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
