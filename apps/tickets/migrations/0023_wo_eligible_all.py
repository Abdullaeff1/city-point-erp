"""A.2: every routing rule is WO-eligible."""

from django.db import migrations


def enable_wo_all(apps, schema_editor):
    RoutingRule = apps.get_model("tickets", "RoutingRule")
    RoutingRule.objects.update(wo_eligible=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0022_sla_policy_a1_hours"),
    ]

    operations = [
        migrations.RunPython(enable_wo_all, noop_reverse),
    ]
