"""Drop property_fm from RolePermission.role choices (users remapped in accounts 0007)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("rbac", "0004_revoke_property_fm_supply_mutations"),
        ("accounts", "0007_retire_property_fm_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rolepermission",
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
                db_index=True,
                max_length=32,
            ),
        ),
    ]
