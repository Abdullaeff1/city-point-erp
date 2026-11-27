# Generated manually for Decision 03 — partial multi-supplier PR line awards.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("procurement", "0006_line_level_sourcing"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="prlineaward",
            name="uniq_active_pr_line_award",
        ),
        migrations.AlterModelOptions(
            name="prlineaward",
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="prlineaward",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True), ("po_line__isnull", True)),
                fields=("pr_line", "supplier_party"),
                name="uniq_active_unissued_pr_line_supplier_award",
            ),
        ),
    ]
