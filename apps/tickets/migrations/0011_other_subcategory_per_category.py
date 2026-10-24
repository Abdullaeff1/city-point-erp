from django.db import migrations

OTHERS = (
    ("technical", "technical-other", "technical", "servicedesk", True, False),
    ("cleaning", "cleaning-other", "cleaning", "servicedesk", False, False),
    ("security", "security-other", "security", "security", False, False),
    ("parking", "parking-other", "parking", "commercial", False, False),
    ("commercial-space", "space-other", "leasing", "commercial", False, True),
    ("lease", "lease-other", "contract", "property", False, False),
    ("billing", "billing-diger", "ar", "accounting", False, False),
    ("administration", "admin-other", "docs", "admin", False, False),
    ("other", "general-other", "general", "servicedesk", False, False),
)


def add_other_choices(apps, schema_editor):
    TicketCategory = apps.get_model("tickets", "TicketCategory")
    TicketSubcategory = apps.get_model("tickets", "TicketSubcategory")
    TicketDepartment = apps.get_model("tickets", "TicketDepartment")
    TicketQueue = apps.get_model("tickets", "TicketQueue")
    RoutingRule = apps.get_model("tickets", "RoutingRule")
    SlaPolicy = apps.get_model("tickets", "SlaPolicy")
    normal = SlaPolicy.objects.filter(priority="normal").first()

    for cat_slug, sub_slug, queue_code, dept_code, wo, crm in OTHERS:
        category = TicketCategory.objects.filter(slug=cat_slug).first()
        queue = TicketQueue.objects.filter(code=queue_code).first()
        department = TicketDepartment.objects.filter(code=dept_code).first()
        if category is None or queue is None or department is None:
            continue
        sub = TicketSubcategory.objects.filter(category=category, slug=sub_slug).first()
        if sub is None:
            sub = TicketSubcategory.objects.create(
                category=category,
                slug=sub_slug,
                name="Digər",
                sort_order=900,
                is_active=True,
                requires_description_min=20,
            )
        else:
            sub.name = "Digər"
            sub.is_active = True
            sub.save(update_fields=["name", "is_active"])
        RoutingRule.objects.update_or_create(
            subcategory=sub,
            defaults={
                "department": department,
                "queue": queue,
                "default_priority": "normal",
                "sla_policy": normal,
                "wo_eligible": wo,
                "crm_eligible": crm,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0010_split_repair_and_new_partition"),
    ]

    operations = [
        migrations.RunPython(add_other_choices, migrations.RunPython.noop),
    ]
