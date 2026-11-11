"""A.1: update SlaPolicy hours — high 4 / normal 8 / low 24 (critical 2)."""

from django.db import migrations


def apply_a1_hours(apps, schema_editor):
    SlaPolicy = apps.get_model("tickets", "SlaPolicy")
    mapping = {
        "critical": (2, "Kritik SLA"),
        "high": (4, "Yüksək SLA"),
        "normal": (8, "Normal SLA"),
        "low": (24, "Aşağı SLA"),
    }
    for priority, (hours, name) in mapping.items():
        SlaPolicy.objects.update_or_create(
            priority=priority,
            defaults={"hours": hours, "name": name, "pause_on_waiting": True},
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0021_az_taxonomy_labels"),
    ]

    operations = [
        migrations.RunPython(apply_a1_hours, noop_reverse),
    ]
