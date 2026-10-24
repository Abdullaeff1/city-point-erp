from django.db import migrations


def split_repair_choices(apps, schema_editor):
    TicketCategory = apps.get_model("tickets", "TicketCategory")
    TicketSubcategory = apps.get_model("tickets", "TicketSubcategory")
    TicketDepartment = apps.get_model("tickets", "TicketDepartment")
    TicketQueue = apps.get_model("tickets", "TicketQueue")
    RoutingRule = apps.get_model("tickets", "RoutingRule")
    SlaPolicy = apps.get_model("tickets", "SlaPolicy")
    Ticket = apps.get_model("tickets", "Ticket")

    technical = TicketCategory.objects.filter(slug="technical").first()
    technical_queue = TicketQueue.objects.filter(code="technical").first()
    desk = TicketDepartment.objects.filter(code="servicedesk").first()
    if technical is None or technical_queue is None or desk is None:
        return
    normal = SlaPolicy.objects.filter(priority="normal").first()

    def ensure(slug, name, sort_order):
        sub, _created = TicketSubcategory.objects.update_or_create(
            category=technical,
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
                "department": desk,
                "queue": technical_queue,
                "default_priority": "normal",
                "sla_policy": normal,
                "wo_eligible": True,
                "crm_eligible": False,
                "is_active": True,
            },
        )
        return sub

    repair = ensure("repair", "Təmir", 60)
    ensure("new-partition", "Yeni Bölgü", 70)
    combined = TicketSubcategory.objects.filter(
        category=technical, slug="repair-new-partition"
    ).first()
    if combined is not None and combined.pk != repair.pk:
        Ticket.objects.filter(subcategory=combined).update(subcategory=repair)
        combined.is_active = False
        combined.save(update_fields=["is_active"])


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0009_fire_security_and_repair_subcategory"),
    ]

    operations = [
        migrations.RunPython(split_repair_choices, migrations.RunPython.noop),
    ]
