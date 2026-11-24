"""Retire Property / FM role — remap users to Təchizat (service_desk)."""

from django.db import migrations, models


def forwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="property_fm").update(role="service_desk")
    RolePermission = apps.get_model("rbac", "RolePermission")
    RolePermission.objects.filter(role="property_fm").delete()
    PurchaseApprovalLimit = apps.get_model("procurement", "PurchaseApprovalLimit")
    # Prefer keeping service_desk row; drop legacy FM limits after merge.
    for lim in PurchaseApprovalLimit.objects.filter(role="property_fm"):
        if PurchaseApprovalLimit.objects.filter(role="service_desk").exists():
            lim.delete()
        else:
            lim.role = "service_desk"
            lim.save(update_fields=["role"])


def backwards(apps, schema_editor):
    # Irreversible user remap — no-op restore of enum only via AlterField reverse.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_backfill_portal_memberships"),
        ("rbac", "0004_revoke_property_fm_supply_mutations"),
        ("procurement", "0006_line_level_sourcing"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("admin", "Admin"),
                    ("management", "Rəhbərlik"),
                    ("reception", "Reception"),
                    ("service_desk", "Təchizat şöbəsi"),
                    ("security", "Təhlükəsizlik"),
                    ("accountant", "Mühasib"),
                    ("sales", "Satış"),
                    ("resident_user", "Rezident"),
                ],
                default="resident_user",
                max_length=32,
            ),
        ),
    ]
