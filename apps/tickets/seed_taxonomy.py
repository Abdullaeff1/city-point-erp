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
        ("hvac", "HVAC Queue", "webservis"),
        ("electric", "Elektrik Queue", "webservis"),
        ("plumbing", "Santexnika Queue", "webservis"),
        ("lift", "Lift Queue", "webservis"),
        ("technical", "Texniki Queue", "webservis"),
        ("cleaning", "Təmizlik Queue", "teserrufat"),
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
                ("fire", "Yanğın sistemi", "technical", TicketPriority.CRITICAL, True, False, 0),
                ("technical-other", "Digər texniki", "technical", TicketPriority.NORMAL, True, False, 20),
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
            ],
        ),
        (
            "commercial-space",
            "Commercial / Space",
            50,
            [
                ("larger-office", "Daha böyük ofis", "leasing", TicketPriority.NORMAL, False, True, 0),
                ("smaller-office", "Daha kiçik ofis", "leasing", TicketPriority.NORMAL, False, True, 0),
                ("additional-office", "Əlavə sahə", "leasing", TicketPriority.NORMAL, False, True, 0),
                ("office-relocation", "Ofis dəyişdirilməsi", "leasing", TicketPriority.NORMAL, False, True, 0),
                ("different-floor", "Başqa mərtəbə", "leasing", TicketPriority.NORMAL, False, True, 0),
                ("new-space", "Yeni sahə", "leasing", TicketPriority.NORMAL, False, True, 0),
            ],
        ),
        (
            "lease",
            "Lease / Contract",
            60,
            [
                ("lease-question", "Müqavilə sualı", "contract", TicketPriority.NORMAL, False, False, 0),
                ("amendment", "Amendment", "contract", TicketPriority.NORMAL, False, False, 0),
                ("renewal", "Renewal", "contract", TicketPriority.NORMAL, False, False, 0),
                ("termination", "Termination", "contract", TicketPriority.HIGH, False, False, 0),
                ("lease-document", "Müqavilə sənədi", "contract", TicketPriority.NORMAL, False, False, 0),
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
                ("billing-other", "Hesablaşma sualı", "ar", TicketPriority.NORMAL, False, False, 0),
            ],
        ),
        (
            "administration",
            "Administration / Documents",
            80,
            [
                ("certificate", "Arayış", "docs", TicketPriority.LOW, False, False, 0),
                ("document-request", "Sənəd tələbi", "docs", TicketPriority.LOW, False, False, 0),
                ("admin-other", "Digər inzibati", "docs", TicketPriority.NORMAL, False, False, 20),
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
                    "sort_order": (i + 1) * 10,
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

    return {"categories": cats, "subcategories": subs, "queues": queues, "departments": depts}
