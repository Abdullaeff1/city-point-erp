"""Seed Ticket taxonomy, departments, queues, and routing rules."""

from apps.tickets.models import (
    RoutingRule,
    SlaPolicy,
    TicketCategory,
    TicketDepartment,
    TicketPriority,
    TicketQueue,
    TicketSubcategory,
)


def seed_ticket_taxonomy():
    """Idempotent seed of Category → Subcategory → RoutingRule matrix."""
    for prio, hours, label in [
        (TicketPriority.CRITICAL, 2, "Kritik SLA"),
        (TicketPriority.HIGH, 8, "Yüksək SLA"),
        (TicketPriority.NORMAL, 24, "Normal SLA"),
        (TicketPriority.LOW, 48, "Aşağı SLA"),
    ]:
        SlaPolicy.objects.update_or_create(
            priority=prio, defaults={"name": label, "hours": hours, "pause_on_waiting": True}
        )

    sla = {p.priority: p for p in SlaPolicy.objects.all()}

    depts = {}
    for code, name in [
        ("webservis", "Webservis / FM"),
        ("teserrufat", "Təsərrüfat"),
        ("security", "Təhlükəsizlik"),
        ("commercial", "Biznesin inkişafı"),
        ("property", "Property / Lease"),
        ("accounting", "Mühasibat"),
        ("admin", "Kargüzarlıq"),
        ("servicedesk", "Service Desk"),
    ]:
        depts[code], _ = TicketDepartment.objects.update_or_create(
            code=code, defaults={"name": name, "is_active": True}
        )

    queues = {}
    for code, name, dept in [
        ("hvac", "HVAC Queue", "servicedesk"),
        ("electric", "Elektrik Queue", "servicedesk"),
        ("plumbing", "Santexnika Queue", "servicedesk"),
        ("lift", "Lift Queue", "servicedesk"),
        ("technical", "Texniki Queue", "servicedesk"),
        ("cleaning", "Təmizlik Queue", "servicedesk"),
        ("security", "Təhlükəsizlik Queue", "security"),
        ("parking", "Parking Queue", "commercial"),
        ("leasing", "Leasing Queue", "commercial"),
        ("contract", "Contract Queue", "property"),
        ("ar", "AR Queue", "accounting"),
        ("docs", "Documents Queue", "admin"),
        ("general", "General Queue", "servicedesk"),
    ]:
        queues[code], _ = TicketQueue.objects.update_or_create(
            code=code,
            defaults={"name": name, "department": depts[dept], "is_active": True},
        )

    # (cat_slug, cat_name, sort, [(sub_slug, sub_name, queue, priority, wo, crm, min_desc)])
    taxonomy = [
        (
            "technical",
            "Texniki / Facility",
            10,
            [
                ("electric", "Elektrik", "electric", TicketPriority.HIGH, True, False, 0),
                ("hvac", "HVAC / Kondisioner", "hvac", TicketPriority.HIGH, True, False, 0),
                ("plumbing", "Santexnika / Su", "plumbing", TicketPriority.HIGH, True, False, 0),
                ("lift", "Lift", "lift", TicketPriority.HIGH, True, False, 0),
                ("generator", "Generator", "technical", TicketPriority.HIGH, True, False, 0),
                ("repair", "Təmir", "technical", TicketPriority.NORMAL, True, False, 0),
                ("new-partition", "Yeni Bölgü", "technical", TicketPriority.NORMAL, True, False, 0),
                ("technical-other", "Digər", "technical", TicketPriority.NORMAL, True, False, 20),
            ],
        ),
        (
            "cleaning",
            "Təmizlik / Təsərrüfat",
            20,
            [
                ("office-cleaning", "Ofis təmizliyi", "cleaning", TicketPriority.NORMAL, False, False, 0),
                ("common-area", "Common area", "cleaning", TicketPriority.NORMAL, False, False, 0),
                ("restroom", "Sanitar qovşaq", "cleaning", TicketPriority.NORMAL, False, False, 0),
                ("waste", "Tullantı", "cleaning", TicketPriority.LOW, False, False, 0),
                ("cleaning-other", "Digər", "cleaning", TicketPriority.NORMAL, False, False, 20),
            ],
        ),
        (
            "security",
            "Təhlükəsizlik",
            30,
            [
                ("security-incident", "Təhlükəsizlik hadisəsi", "security", TicketPriority.CRITICAL, False, False, 0),
                ("suspicious", "Şübhəli hal", "security", TicketPriority.HIGH, False, False, 0),
                ("access-fault", "Access problemi (nasazlıq)", "security", TicketPriority.HIGH, True, False, 0),
                ("card-order", "Yeni əməkdaş — kart sifarişi", "security", TicketPriority.NORMAL, False, False, 0),
                ("fire", "Yanğın sistemi", "security", TicketPriority.CRITICAL, True, False, 0),
                ("cargo", "Yük daşıma", "security", TicketPriority.NORMAL, False, False, 0),
                ("event", "Tədbir", "security", TicketPriority.NORMAL, False, False, 0),
                ("security-other", "Digər", "security", TicketPriority.NORMAL, False, False, 20),
            ],
        ),
        (
            "parking",
            "Parking",
            40,
            [
                ("parking-issue", "Parking problemi", "parking", TicketPriority.NORMAL, False, False, 0),
                ("parking-change", "Mövcud parking dəyişiklik", "parking", TicketPriority.NORMAL, False, True, 0),
                ("parking-extra", "Əlavə parking tələbi", "parking", TicketPriority.NORMAL, False, True, 0),
                ("parking-other", "Digər", "parking", TicketPriority.NORMAL, False, False, 20),
            ],
        ),
        (
            "commercial-space",
            "Commercial / Space",
            50,
            [
                ("larger-office", "Daha böyük ofis", "leasing", TicketPriority.NORMAL, False, True, 0),
                ("smaller-office", "Daha kiçik ofis", "leasing", TicketPriority.NORMAL, False, True, 0),
                ("office-relocation", "Ofis dəyişdirilməsi", "leasing", TicketPriority.NORMAL, False, True, 0),
                ("new-space", "Yeni sahə", "leasing", TicketPriority.NORMAL, False, True, 0),
                ("space-other", "Digər", "leasing", TicketPriority.NORMAL, False, True, 20),
            ],
        ),
        (
            "lease",
            "Lease / Contract",
            60,
            [
                ("amendment", "Amendment", "contract", TicketPriority.NORMAL, False, False, 0),
                ("renewal", "Renewal", "contract", TicketPriority.NORMAL, False, False, 0),
                ("termination", "Termination", "contract", TicketPriority.HIGH, False, False, 0),
                ("lease-document", "Müqavilə sənədi", "contract", TicketPriority.NORMAL, False, False, 0),
                ("lease-matter", "Müqavilə ilə bağlı", "contract", TicketPriority.NORMAL, False, False, 0),
                ("additional-agreement", "Əlavə razılaşma", "contract", TicketPriority.NORMAL, False, False, 0),
                ("lease-other", "Digər", "contract", TicketPriority.NORMAL, False, False, 20),
            ],
        ),
        (
            "billing",
            "Billing / Finance",
            70,
            [
                ("invoice", "Invoice", "ar", TicketPriority.NORMAL, False, False, 0),
                ("payment", "Ödəniş", "ar", TicketPriority.NORMAL, False, False, 0),
                ("service-charge", "Service charge", "ar", TicketPriority.NORMAL, False, False, 0),
                ("debt", "Borc", "ar", TicketPriority.HIGH, False, False, 0),
                ("rent-payment", "İcarə ödənişi", "ar", TicketPriority.NORMAL, False, False, 0),
                ("extra-services-payment", "Əlavə xidmətlər ödənişi", "ar", TicketPriority.NORMAL, False, False, 0),
                ("deposit", "Depozit", "ar", TicketPriority.NORMAL, False, False, 0),
                ("billing-other", "Hesablaşma sualı", "ar", TicketPriority.NORMAL, False, False, 0),
                ("billing-diger", "Digər", "ar", TicketPriority.NORMAL, False, False, 20),
            ],
        ),
        (
            "administration",
            "Administration / Documents",
            80,
            [
                ("certificate", "Arayış", "docs", TicketPriority.LOW, False, False, 0),
                ("document-request", "Sənəd tələbi", "docs", TicketPriority.LOW, False, False, 0),
                ("admin-other", "Digər", "docs", TicketPriority.NORMAL, False, False, 20),
            ],
        ),
        (
            "other",
            "Other",
            90,
            [
                ("general-other", "Digər", "general", TicketPriority.NORMAL, False, False, 40),
            ],
        ),
    ]

    cats = {}
    subs = {}
    for cat_slug, cat_name, sort, sub_rows in taxonomy:
        cat, _ = TicketCategory.objects.update_or_create(
            slug=cat_slug,
            defaults={"name": cat_name, "sort_order": sort, "is_active": True},
        )
        cats[cat_slug] = cat
        for i, (sub_slug, sub_name, qcode, prio, wo, crm, min_desc) in enumerate(sub_rows):
            sub, _ = TicketSubcategory.objects.update_or_create(
                category=cat,
                slug=sub_slug,
                defaults={
                    "name": sub_name,
                    "sort_order": 1000 if sub_name == "Digər" else (i + 1) * 10,
                    "is_active": True,
                    "requires_description_min": min_desc,
                },
            )
            subs[f"{cat_slug}:{sub_slug}"] = sub
            RoutingRule.objects.update_or_create(
                subcategory=sub,
                defaults={
                    "department": queues[qcode].department,
                    "queue": queues[qcode],
                    "default_priority": prio,
                    "sla_policy": sla.get(prio),
                    "wo_eligible": wo,
                    "crm_eligible": crm,
                    "is_active": True,
                },
            )

    # Keep non-colliding legacy slugs for old FK references (do not overwrite new taxonomy).
    legacy_map = {
        "hvac": "HVAC (legacy)",
        "electric": "Elektrik (legacy)",
        "access": "Access (legacy)",
    }
    taxonomy_slugs = {row[0] for row in taxonomy}
    for legacy_slug, legacy_name in legacy_map.items():
        if legacy_slug in taxonomy_slugs:
            continue
        legacy_cat, _ = TicketCategory.objects.update_or_create(
            slug=legacy_slug,
            defaults={"name": legacy_name, "sort_order": 900, "is_active": False},
        )
        cats[legacy_slug] = legacy_cat

    _retire_technical_fire(cats, subs)
    _retire_combined_repair(cats, subs)
    TicketSubcategory.objects.filter(
        category=cats["commercial-space"],
        slug__in=("additional-office", "different-floor"),
    ).update(is_active=False)
    TicketSubcategory.objects.filter(category=cats["lease"], slug="lease-question").update(
        is_active=False
    )
    return {"categories": cats, "subcategories": subs, "queues": queues, "departments": depts}


def _retire_technical_fire(cats, subs):
    """Older seeds kept Yanğın sistemi under Texniki. Tickets now belong to Təhlükəsizlik."""
    from apps.tickets.models import Ticket

    current = subs.get("security:fire")
    old = TicketSubcategory.objects.filter(category=cats["technical"], slug="fire").first()
    if old is None or current is None or old.pk == current.pk:
        return
    Ticket.objects.filter(subcategory=old).update(subcategory=current, category=cats["security"])
    old.is_active = False
    old.save(update_fields=["is_active"])


def _retire_combined_repair(cats, subs):
    """The first version stored Təmir and Yeni Bölgü as one choice."""
    from apps.tickets.models import Ticket

    repair = subs.get("technical:repair")
    combined = TicketSubcategory.objects.filter(
        category=cats["technical"], slug="repair-new-partition"
    ).first()
    if combined is None or repair is None or combined.pk == repair.pk:
        return
    Ticket.objects.filter(subcategory=combined).update(subcategory=repair)
    combined.is_active = False
    combined.save(update_fields=["is_active"])
