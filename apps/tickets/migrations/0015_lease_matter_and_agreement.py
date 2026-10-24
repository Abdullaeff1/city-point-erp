from django.db import migrations

NEW_SUBS = (
    ("lease-matter", "Müqavilə ilə bağlı", 60),
    ("additional-agreement", "Əlavə razılaşma", 70),
)


def add_lease_subs(apps, schema_editor):
    TicketCategory = apps.get_model("tickets", "TicketCategory")
    TicketSubcategory = apps.get_model("tickets", "TicketSubcategory")
    TicketDepartment = apps.get_model("tickets", "TicketDepartment")
    TicketQueue = apps.get_model("tickets", "TicketQueue")
    RoutingRule = apps.get_model("tickets", "RoutingRule")
    SlaPolicy = apps.get_model("tickets", "SlaPolicy")

    category = TicketCategory.objects.filter(slug="lease").first()
    department = TicketDepartment.objects.filter(code="property").first()
    queue = TicketQueue.objects.filter(code="contract").first()
    if category is None or department is None or queue is None:
        return
    normal = SlaPolicy.objects.filter(priority="normal").first()
    for slug, name, sort_order in NEW_SUBS:
        sub, _created = TicketSubcategory.objects.update_or_create(
            category=category,
            slug=slug,
            defaults={
                "name": name,
                "sort_order": sort_order,
                "is_active": True,
                "requires_description_min": 0,
            },
        )
        RoutingRule.objects.update_or_create(
            subcategory=sub,
            defaults={
                "department": department,
                "queue": queue,
                "default_priority": "normal",
                "sla_policy": normal,
                "wo_eligible": False,
                "crm_eligible": False,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0014_hide_extra_space_and_floor"),
    ]

    operations = [
        migrations.RunPython(add_lease_subs, migrations.RunPython.noop),
    ]
