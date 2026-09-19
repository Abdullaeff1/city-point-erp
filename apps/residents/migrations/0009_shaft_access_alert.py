# Generated manually for ShaftAccessAlert

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("residents", "0008_accessevent_reader"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShaftAccessAlert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("employee_name", models.CharField(max_length=160)),
                ("card_number", models.CharField(blank=True, max_length=32)),
                ("company_id", models.PositiveIntegerField(blank=True, db_index=True, null=True)),
                ("company_name", models.CharField(blank=True, max_length=160)),
                ("occurred_at", models.DateTimeField(db_index=True)),
                ("event_type", models.CharField(choices=[("in", "Giriş"), ("out", "Çıxış")], max_length=8)),
                ("reader_id", models.PositiveIntegerField(blank=True, null=True)),
                ("reader_name", models.CharField(blank=True, max_length=160)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                (
                    "access_event",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shaft_alert",
                        to="residents.accessevent",
                    ),
                ),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="acknowledged_shaft_access_alerts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shaft_access_alerts",
                        to="residents.residentemployee",
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="shaftaccessalert",
            index=models.Index(fields=["acknowledged_at", "occurred_at"], name="residents_s_acknowl_shaft_idx"),
        ),
    ]
