# Generated manually for visitor management expansion

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def split_guest_names(apps, schema_editor):
    Guest = apps.get_model("reception", "Guest")
    for guest in Guest.objects.all():
        if guest.first_name or guest.last_name:
            if not guest.full_name:
                guest.full_name = f"{guest.first_name} {guest.last_name}".strip()
                guest.save(update_fields=["full_name"])
            continue
        name = (guest.full_name or "").strip()
        if not name:
            continue
        parts = name.split(None, 1)
        guest.first_name = parts[0][:80]
        guest.last_name = (parts[1] if len(parts) > 1 else "")[:80]
        guest.save(update_fields=["first_name", "last_name"])


def seed_visitor_types(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    defaults = [
        ("resident-meeting", "Resident Meeting", 10),
        ("delivery", "Delivery", 20),
        ("contractor", "Contractor", 30),
        ("service-provider", "Service Provider", 40),
        ("interview", "Interview", 50),
        ("official-guest", "Official Guest", 60),
        ("other", "Other", 70),
    ]
    for code, name, order in defaults:
        VisitorType.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": order, "is_active": True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0003_scope1_12_domains"),
        ("residents", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VisitorType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(unique=True)),
                ("name", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
            ],
            options={"ordering": ["sort_order", "name"]},
        ),
        migrations.AddField(
            model_name="guest",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="guest",
            name="fin_code",
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
        migrations.AddField(
            model_name="guest",
            name="first_name",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="guest",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="guest",
            name="last_name",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="guest",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name="guest",
            name="full_name",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.RunPython(split_guest_names, migrations.RunPython.noop),
        migrations.AddField(
            model_name="guestvisit",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_guest_visits",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="guestvisit",
            name="document_note",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="guestvisit",
            name="id_document_held",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="guestvisit",
            name="id_document_returned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="guestvisit",
            name="id_override_reason",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="guestvisit",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="guestvisit",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name="guestvisit",
            name="visit_type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="visits",
                to="reception.visitortype",
            ),
        ),
        migrations.AlterField(
            model_name="guestvisit",
            name="status",
            field=models.CharField(
                choices=[
                    ("pre_registered", "Əvvəlcədən qeyd"),
                    ("waiting", "Gözləyir"),
                    ("inside", "İçəridə"),
                    ("left", "Çıxış edib"),
                    ("cancelled", "Ləğv"),
                    ("no_show", "Gəlməyib"),
                    ("return_pending", "Vəsiqə gözləyir"),
                ],
                default="waiting",
                max_length=16,
            ),
        ),
        migrations.AlterModelOptions(
            name="guest",
            options={"ordering": ["last_name", "first_name", "full_name"]},
        ),
        migrations.AlterModelOptions(
            name="guestvisit",
            options={"ordering": ["-check_in_at", "-created_at"]},
        ),
        migrations.CreateModel(
            name="VisitorAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(default="mock", max_length=64)),
                ("external_id", models.CharField(blank=True, max_length=128)),
                ("credential", models.CharField(blank=True, max_length=128)),
                ("valid_from", models.DateTimeField(blank=True, null=True)),
                ("valid_until", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("active", "Active"),
                            ("expired", "Expired"),
                            ("revoked", "Revoked"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "sync_status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("success", "Success"), ("error", "Error")],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("last_sync_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "visit",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="visitor_access",
                        to="reception.guestvisit",
                    ),
                ),
            ],
        ),
        migrations.RunPython(seed_visitor_types, migrations.RunPython.noop),
    ]
