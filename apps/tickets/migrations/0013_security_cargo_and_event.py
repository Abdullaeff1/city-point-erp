from django.db import migrations

NEW_SUBS = (
    ("cargo", "Yük daşıma", 60),
    ("event", "Tədbir", 70),
)


def add_security_subs(apps, schema_editor):
    TicketCategory = apps.get_model("tickets", "TicketCategory")
    TicketSubcategory = apps.get_model("tickets", "TicketSubcategory")
    TicketDepartment = apps.get_model("tickets", "TicketDepartment")
    TicketQueue = apps.get_model("tickets", "TicketQueue")
    RoutingRule = apps.get_model("tickets", "RoutingRule")
    SlaPolicy = apps.get_model("tickets", "SlaPolicy")

    category = TicketCategory.objects.filter(slug="security").first()
    department = TicketDepartment.objects.filter(code="security").first()
    queue = TicketQueue.objects.filter(code="security").first()
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
        ("tickets", "0012_other_subcategory_last"),
    ]

    operations = [
        migrations.RunPython(add_security_subs, migrations.RunPython.noop),
    ]
