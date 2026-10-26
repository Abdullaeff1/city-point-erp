from django.db import migrations


def add_card_related(apps, schema_editor):
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
    sub, _created = TicketSubcategory.objects.update_or_create(
        category=category,
        slug="card-related",
        defaults={
            "name": "Kartla bağlı",
            "sort_order": 45,
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
        ("tickets", "0018_suggestion_ticket_type"),
    ]

    operations = [
        migrations.RunPython(add_card_related, migrations.RunPython.noop),
    ]
