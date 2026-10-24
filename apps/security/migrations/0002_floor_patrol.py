import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("security_portal", "0001_floor_plans"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FloorPatrolSheet",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("night_date", models.DateField(unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Qaralama"),
                            ("open", "Açıq"),
                            ("closed", "Bağlı"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_floor_patrol_sheets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_floor_patrol_sheets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-night_date"]},
        ),
        migrations.CreateModel(
            name="FloorPatrolRound",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("floor_code", models.CharField(max_length=8)),
                ("slot", models.CharField(max_length=5)),
                ("started_at", models.TimeField(blank=True, null=True)),
                ("ended_at", models.TimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("waiting", "Gözləyir"),
                            ("in_progress", "İcradadır"),
                            ("completed", "Tamamlandı"),
                            ("missed", "YOX"),
                        ],
                        default="waiting",
                        max_length=16,
                    ),
                ),
                ("inspector_name", models.CharField(blank=True, max_length=80)),
                ("note", models.CharField(blank=True, max_length=240)),
                (
                    "sheet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rounds",
                        to="security_portal.floorpatrolsheet",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="FloorPatrolMark",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("floor_code", models.CharField(max_length=8)),
                ("row_index", models.PositiveSmallIntegerField()),
                ("inspector_name", models.CharField(blank=True, max_length=80)),
                (
                    "sheet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="marks",
                        to="security_portal.floorpatrolsheet",
                    ),
                ),
            ],
            options={"ordering": ["floor_code", "row_index"]},
        ),
        migrations.AddConstraint(
            model_name="floorpatrolround",
            constraint=models.UniqueConstraint(
                fields=("sheet", "floor_code", "slot"),
                name="uniq_floor_patrol_round_slot",
            ),
        ),
        migrations.AddConstraint(
            model_name="floorpatrolmark",
            constraint=models.UniqueConstraint(
                fields=("sheet", "floor_code", "row_index"),
                name="uniq_floor_patrol_mark_row",
            ),
        ),
    ]
