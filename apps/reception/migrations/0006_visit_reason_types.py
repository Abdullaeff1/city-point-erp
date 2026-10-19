from django.db import migrations


REASON_TYPES = [
    ("courier", "Kuryer", 10),
    ("forgotten-card", "Kartın unutmuş əməkdaş", 20),
    ("guest", "Qonaq", 30),
    ("lease-area", "İcarə sahə üçün", 40),
    ("meeting", "Meeting room", 50),
    ("goods-handover", "Məhsul təhvil-təslimi üçün", 60),
    ("technician", "Usta/texniki işçi", 70),
]

LEGACY_CODES = {
    "resident-meeting",
    "delivery",
    "contractor",
    "service-provider",
    "interview",
    "official-guest",
    "other",
}


def seed_reason_types(apps, schema_editor):
    VisitorType = apps.get_model("reception", "VisitorType")
    keep_codes = {code for code, _, _ in REASON_TYPES}
    for code, name, order in REASON_TYPES:
        obj, created = VisitorType.objects.get_or_create(
            code=code,
            defaults={"name": name, "sort_order": order, "is_active": True},
        )
        if not created:
            obj.name = name
            obj.sort_order = order
            obj.is_active = True
            obj.save(update_fields=["name", "sort_order", "is_active"])
    VisitorType.objects.filter(code__in=LEGACY_CODES - keep_codes).update(is_active=False)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("reception", "0005_guest_serial_verbose"),
    ]

    operations = [
        migrations.RunPython(seed_reason_types, noop_reverse),
    ]
