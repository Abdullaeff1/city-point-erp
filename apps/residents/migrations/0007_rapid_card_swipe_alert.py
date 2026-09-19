import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("residents", "0006_employee_access_level"),
    ]

    operations = [
        migrations.CreateModel(
            name="RapidCardSwipeAlert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("employee_name", models.CharField(max_length=160)),
                ("card_number", models.CharField(blank=True, max_length=32)),
                ("company_id", models.PositiveIntegerField(blank=True, db_index=True, null=True)),
                ("company_name", models.CharField(blank=True, max_length=160)),
                ("window_start", models.DateTimeField()),
                ("window_end", models.DateTimeField()),
                ("swipe_count", models.PositiveIntegerField()),
                ("swipes", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="acknowledged_rapid_swipe_alerts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rapid_swipe_alerts",
                        to="residents.residentemployee",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="rapidcardswipealert",
            index=models.Index(fields=["employee", "window_start"], name="residents_r_employe_7a2c1d_idx"),
        ),
        migrations.AddIndex(
            model_name="rapidcardswipealert",
            index=models.Index(fields=["acknowledged_at", "created_at"], name="residents_r_acknowl_9b4e2f_idx"),
        ),
        migrations.AddConstraint(
            model_name="rapidcardswipealert",
            constraint=models.UniqueConstraint(
                fields=("employee", "window_start"),
                name="uniq_rapid_swipe_employee_window_start",
            ),
        ),
    ]
