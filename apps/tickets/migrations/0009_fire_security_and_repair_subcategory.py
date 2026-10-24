from django.db import migrations


def move_fire_and_add_repair(apps, schema_editor):
    TicketCategory = apps.get_model("tickets", "TicketCategory")
    TicketSubcategory = apps.get_model("tickets", "TicketSubcategory")
    TicketDepartment = apps.get_model("tickets", "TicketDepartment")
    TicketQueue = apps.get_model("tickets", "TicketQueue")
    RoutingRule = apps.get_model("tickets", "RoutingRule")
    SlaPolicy = apps.get_model("tickets", "SlaPolicy")
    Ticket = apps.get_model("tickets", "Ticket")

    technical = TicketCategory.objects.filter(slug="technical").first()
    security_cat = TicketCategory.objects.filter(slug="security").first()
    security_dept = TicketDepartment.objects.filter(code="security").first()
    security_queue = TicketQueue.objects.filter(code="security").first()
    if security_cat is None or security_dept is None or security_queue is None:
        return

    fire = None
    if technical is not None:
        fire = TicketSubcategory.objects.filter(category=technical, slug="fire").first()
    parked = TicketSubcategory.objects.filter(category=security_cat, slug="fire").first()
    if fire and parked and fire.pk != parked.pk:
        Ticket.objects.filter(subcategory=fire).update(subcategory=parked, category=security_cat)
        fire.is_active = False
        fire.save(update_fields=["is_active"])
        fire = parked
    elif fire is not None:
        fire.category = security_cat
        fire.is_active = True
        fire.name = "Yanğın sistemi"
        fire.save(update_fields=["category", "is_active", "name"])
    elif parked is not None:
        fire = parked
    else:
        fire = TicketSubcategory.objects.create(
            category=security_cat,
            slug="fire",
            name="Yanğın sistemi",
            sort_order=50,
            is_active=True,
            requires_description_min=0,
        )

    RoutingRule.objects.update_or_create(
        subcategory=fire,
        defaults={
            "department": security_dept,
            "queue": security_queue,
            "default_priority": "critical",
            "sla_policy": SlaPolicy.objects.filter(priority="critical").first(),
            "wo_eligible": True,
            "crm_eligible": False,
            "is_active": True,
        },
    )
    Ticket.objects.filter(subcategory=fire).update(
        category=security_cat,
        department=security_dept,
        queue=security_queue,
    )

    technical_queue = TicketQueue.objects.filter(code="technical").first()
    desk = TicketDepartment.objects.filter(code="servicedesk").first()
    if technical is None or technical_queue is None or desk is None:
        return
    repair, _created = TicketSubcategory.objects.update_or_create(
        category=technical,
        slug="repair-new-partition",
        defaults={
            "name": "Təmir, (Yeni Bölgü)",
            "sort_order": 65,
            "is_active": True,
            "requires_description_min": 0,
        },
    )
    RoutingRule.objects.update_or_create(
        subcategory=repair,
        defaults={
            "department": desk,
            "queue": technical_queue,
            "default_priority": "normal",
            "sla_policy": SlaPolicy.objects.filter(priority="normal").first(),
            "wo_eligible": True,
            "crm_eligible": False,
            "is_active": True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0008_ticket_assigned_employee"),
    ]

    operations = [
        migrations.RunPython(move_fire_and_add_repair, migrations.RunPython.noop),
    ]
