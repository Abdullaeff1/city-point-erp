"""Revoke legacy PROPERTY_FM warehouse/procurement mutate RolePermission rows.

Repeatable via apps.rbac.services.reconcile_property_fm_supply_mutations /
seed_rbac_catalog. Does not touch UserPermission (independent grants).
"""

from django.db import migrations


def forwards(apps, schema_editor):
    RolePermission = apps.get_model("rbac", "RolePermission")
    PermissionCode = apps.get_model("rbac", "PermissionCode")
    revoked = ("warehouse.edit", "procurement.edit", "procurement.approve")
    perm_ids = list(
        PermissionCode.objects.filter(code__in=revoked).values_list("id", flat=True)
    )
    if not perm_ids:
        return
    RolePermission.objects.filter(role="property_fm", permission_id__in=perm_ids).delete()


def backwards(apps, schema_editor):
    """Restore RolePermission rows for PROPERTY_FM (pre-Supply cutover defaults)."""
    RolePermission = apps.get_model("rbac", "RolePermission")
    PermissionCode = apps.get_model("rbac", "PermissionCode")
    for code in ("warehouse.edit", "procurement.edit", "procurement.approve"):
        perm = PermissionCode.objects.filter(code=code).first()
        if perm is None:
            continue
        RolePermission.objects.get_or_create(role="property_fm", permission=perm)


class Migration(migrations.Migration):

    dependencies = [
        ("rbac", "0003_supply_directory_contact_position"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
