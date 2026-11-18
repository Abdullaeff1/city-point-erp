"""Restore wo_eligible from taxonomy: technical + fire only (not all rules)."""

from django.db import migrations
from django.db.models import Q


def restore_wo_flags(apps, schema_editor):
    RoutingRule = apps.get_model("tickets", "RoutingRule")
    RoutingRule.objects.update(wo_eligible=False)
    RoutingRule.objects.filter(
        Q(subcategory__category__slug="technical") | Q(subcategory__slug="fire")
    ).update(wo_eligible=True)


def revert_wo_all(apps, schema_editor):
    RoutingRule = apps.get_model("tickets", "RoutingRule")
    RoutingRule.objects.update(wo_eligible=True)


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0024_ticket_escalation_level"),
    ]

    operations = [
        migrations.RunPython(restore_wo_flags, revert_wo_all),
    ]
