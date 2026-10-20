from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.timezone import make_aware

from apps.accounts.models import Role, User
from apps.comms.models import Announcement, AnnouncementSeverity, Notification
from apps.documents.models import Document
from apps.property.models import Asset, Building, Contractor, Floor, Occupancy, Space
from apps.residents.models import AccessEvent, AccessEventType, ResidentCompany, ResidentEmployee
from apps.integrations.models import ExternalIdentity
from apps.tickets.models import (
    SlaPolicy,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketPriority,
    TicketStatus,
    TicketType,
)
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import route_ticket


class Command(BaseCommand):
    help = "PPTX nümunə məlumatlarını yükləyir (təkrar işlətmək təhlükəsizdir)."

    def handle(self, *args, **options):
        building, _ = Building.objects.get_or_create(code="CP", defaults={"name": "City Point Business Center"})
        f08, _ = Floor.objects.get_or_create(building=building, code="F08", defaults={"name": "8-ci mərtəbə"})
        f05, _ = Floor.objects.get_or_create(building=building, code="F05", defaults={"name": "5-ci mərtəbə"})
        f03, _ = Floor.objects.get_or_create(building=building, code="F03", defaults={"name": "3-cü mərtəbə"})
        f01, _ = Floor.objects.get_or_create(building=building, code="F01", defaults={"name": "1-ci mərtəbə"})

        asbc, _ = ResidentCompany.objects.update_or_create(
            slug="asbc",
            defaults={
                "name": "ASBC",
                "status": "active",
                "portal_active": True,
                "contact_email": "office@asbc.az",
                "contract_start": date(2025, 1, 1),
                "contract_end": date(2027, 12, 31),
            },
        )
        techco, _ = ResidentCompany.objects.update_or_create(
            slug="techco",
            defaults={
                "name": "TechCo",
                "status": "active",
                "portal_active": True,
                "contact_email": "hello@techco.az",
            },
        )

        space801, _ = Space.objects.update_or_create(
            code="CP-F08-OFF-801",
            defaults={
                "name": "801",
                "floor": f08,
                "resident": asbc,
                "area_m2": "182.4",
                "access_zone": "F08-A",
                "occupancy": Occupancy.ACTIVE_LEASE,
                "commercial_status": "active",
                "operational_status": "available",
                "rentable_area_m2": "182.4",
                "cost_center": "CC-F08-801",
                "plan_revision": "Rev.04",
            },
        )
        lobby, _ = Space.objects.update_or_create(
            code="CP-F01-LOB-001",
            defaults={
                "name": "Lobby",
                "floor": f01,
                "area_m2": "240.0",
                "access_zone": "F01",
                "commercial_status": "vacant",
                "operational_status": "available",
            },
        )
        vacant_office, _ = Space.objects.update_or_create(
            code="CP-F05-OFF-502",
            defaults={
                "name": "502",
                "floor": f05,
                "area_m2": "96.0",
                "rentable_area_m2": "96.0",
                "occupancy": Occupancy.VACANT,
                "commercial_status": "vacant",
                "operational_status": "available",
                "is_public": True,
                "public_description": "Bright office on floor 5, ready to lease.",
            },
        )

        for i, name in enumerate(
            [
                "HVAC daxili blok",
                "Access oxuyucu",
                "LED panel",
                "Yanğın detektoru",
                "Su sayğacı",
                "Elektrik sayğacı",
            ],
            start=1,
        ):
            Asset.objects.get_or_create(space=space801, name=name, defaults={"asset_code": f"A-801-{i:02d}"})
        for extra in range(7, 15):
            Asset.objects.get_or_create(
                space=space801, name=f"Avadanlıq {extra}", defaults={"asset_code": f"A-801-{extra:02d}"}
            )

        Contractor.objects.get_or_create(name="CityPoint FM", defaults={"contact_email": "fm@citypoint.az"})

        employees = {}
        # Prefer real AxTrax-synced ASBC staff; do not recreate demo AC-* card fakes.
        asbc_real = list(
            ResidentEmployee.objects.filter(company=asbc, is_active=True)
            .exclude(card_number="")
            .order_by("id")[:5]
        )
        if len(asbc_real) >= 2:
            for emp in asbc_real:
                employees[emp.full_name] = emp
            default_asbc_host = asbc_real[0]
        else:
            default_asbc_host = None

        today = timezone.localdate()
        tz = timezone.get_current_timezone()

        def at_hour(h, m=0):
            return make_aware(datetime.combine(today, time(h, m)), tz)

        # Demo AccessEvent only when ASBC has no AxTrax-linked employees yet.
        from django.contrib.contenttypes.models import ContentType

        emp_ct = ContentType.objects.get_for_model(ResidentEmployee)
        axtrax_emp_ids = ExternalIdentity.objects.filter(
            system="axtraxng",
            external_id__startswith="emp:",
            entity_type=emp_ct,
        ).values_list("entity_id", flat=True)
        has_axtrax_asbc = ResidentEmployee.objects.filter(company=asbc, id__in=axtrax_emp_ids).exists()
        if (
            not has_axtrax_asbc
            and default_asbc_host
            and not AccessEvent.objects.filter(employee__company=asbc, occurred_at__date=today).exists()
        ):
            AccessEvent.objects.bulk_create(
                [
                    AccessEvent(
                        employee=default_asbc_host,
                        event_type=AccessEventType.IN,
                        occurred_at=at_hour(8, 52),
                    ),
                ]
            )

        tax = seed_ticket_taxonomy()
        cats = tax["categories"]
        subs = tax["subcategories"]

        # Prefer new taxonomy for demo tickets; keep legacy slug keys for upsert helper.
        demo_cats = {
            "hvac": cats["technical"],
            "electric": cats["technical"],
            "cleaning": cats["cleaning"],
            "access": cats["security"],
            "larger-office": cats["commercial-space"],
        }
        demo_subs = {
            "hvac": subs["technical:hvac"],
            "electric": subs["technical:electric"],
            "cleaning": subs["cleaning:office-cleaning"],
            "access": subs["security:access-fault"],
            "larger-office": subs["commercial-space:larger-office"],
        }

        # Demo staff → ticket_department (Role ≠ dept in production; seed only).
        from apps.tickets.models import TicketDepartment

        dept_by_code = {d.code: d for d in TicketDepartment.objects.all()}
        staff_map = {
            # uname: email, first_name, role, password, ticket_department_code|None
            "admin": ("admin@citypoint.az", "Admin", Role.ADMIN, "admin123", None),
            "reception": ("reception@citypoint.az", "Reception", Role.RECEPTION, "reception123", None),
            "desk": ("desk@citypoint.az", "Service Desk", Role.SERVICE_DESK, "desk123", "servicedesk"),
            "fm": ("fm@citypoint.az", "Property FM", Role.PROPERTY_FM, "fm123", "webservis"),
            "manager": ("manager@citypoint.az", "Rəhbərlik", Role.MANAGEMENT, "manager123", None),
            "security": ("security@citypoint.az", "Təhlükəsizlik", Role.SECURITY, "security123", "security"),
        }
        created_users = {}
        for uname, (email, first, role, password, dept_code) in staff_map.items():
            user, _created = User.objects.get_or_create(
                email=email,
                defaults={
                    "username": uname,
                    "first_name": first,
                    "role": role,
                    "is_staff": True,
                    "is_superuser": role == Role.ADMIN,
                },
            )
            user.role = role
            user.is_staff = True
            if role == Role.ADMIN:
                user.is_superuser = True
            if dept_code and dept_code in dept_by_code:
                user.ticket_department = dept_by_code[dept_code]
            user.set_password(password)
            user.save()
            created_users[uname] = user

        portal_user, _ = User.objects.get_or_create(
            email="office@asbc.az",
            defaults={"username": "asbc", "first_name": "ASBC", "role": Role.RESIDENT_USER, "resident_company": asbc},
        )
        portal_user.role = Role.RESIDENT_USER
        portal_user.resident_company = asbc
        portal_user.set_password("asbc123")
        portal_user.save()

        desk = created_users["desk"]
        fm = created_users["fm"]
        security_user = created_users["security"]
        now = timezone.now()

        def _seed_assignee_for(ticket):
            """Assignee must be from the routed department (not always Service Desk)."""
            code = getattr(ticket.department, "code", None)
            if code in {"webservis", "teserrufat", "property"}:
                return fm
            if code == "security":
                return security_user
            if code == "servicedesk":
                return desk
            return None

        def upsert_ticket(code, cat_key, company, space, prio, status, desc, sla_hours, ticket_type=None):
            ttype = ticket_type or (
                TicketType.COMMERCIAL if cat_key == "larger-office" else TicketType.INCIDENT
            )
            ticket, _ = Ticket.objects.update_or_create(
                code=code,
                defaults={
                    "ticket_type": ttype,
                    "category": demo_cats[cat_key],
                    "subcategory": demo_subs[cat_key],
                    "company": company,
                    "space": space,
                    "requester": portal_user if company == asbc else None,
                    "assignee": None,
                    "priority": prio,
                    "status": status,
                    "description": desc,
                    "sla_due_at": now + timedelta(hours=sla_hours),
                },
            )
            route_ticket(ticket, actor=desk, note="seed", apply_default_priority=False)
            if status in {TicketStatus.IN_PROGRESS, TicketStatus.ACCEPTED, TicketStatus.ASSIGNED}:
                ticket.assignee = _seed_assignee_for(ticket)
                ticket.save(update_fields=["assignee", "updated_at"])
            TicketMessage.objects.get_or_create(
                ticket=ticket,
                body=desc,
                defaults={
                    "author": portal_user if company == asbc else desk,
                    "author_label": "Siz" if company == asbc else "CityPoint",
                },
            )
            return ticket

        t1042 = upsert_ticket(
            "TK-1042",
            "hvac",
            asbc,
            space801,
            TicketPriority.HIGH,
            TicketStatus.IN_PROGRESS,
            "Kondisioner soyutmur, otaq isti qalır.",
            4,
        )
        TicketMessage.objects.get_or_create(
            ticket=t1042,
            body="Müraciət qəbul edildi, texniki komanda təyin olunub.",
            defaults={"author": desk, "author_label": "CityPoint"},
        )
        TicketMessage.objects.get_or_create(
            ticket=t1042,
            body="Bu gün 14:00-16:00 arası yoxlanılacaq.",
            defaults={"author": desk, "author_label": "Texnik"},
        )
        upsert_ticket("TK-1040", "electric", asbc, None, TicketPriority.NORMAL, TicketStatus.SENT, "Koridor F03 işıqları yanıb-sönür.", 24)
        upsert_ticket("TK-1038", "access", asbc, space801, TicketPriority.NORMAL, TicketStatus.RESOLVED, "Access kart yenilənməsi.", 24)
        upsert_ticket("TK-1035", "access", techco, None, TicketPriority.NORMAL, TicketStatus.ACCEPTED, "Yeni əməkdaş üçün kart.", 24)
        upsert_ticket("TK-1031", "cleaning", asbc, lobby, TicketPriority.LOW, TicketStatus.IN_PROGRESS, "F01 Lobby təmizlik.", 48)
        upsert_ticket("TK-1021", "cleaning", asbc, space801, TicketPriority.NORMAL, TicketStatus.RESOLVED, "Ofis təmizliyi.", 24)
        upsert_ticket("TK-1010", "electric", asbc, space801, TicketPriority.NORMAL, TicketStatus.RESOLVED, "Rozetka nasazlığı.", 24)
        upsert_ticket(
            "TK-1050",
            "larger-office",
            asbc,
            space801,
            TicketPriority.NORMAL,
            TicketStatus.SENT,
            "Hazırkı ofisimiz kiçikdir, daha böyük sahə istəyirik.",
            24,
            ticket_type=TicketType.COMMERCIAL,
        )

        Notification.objects.get_or_create(user=portal_user, ticket=t1042, message="TK-1042 statusu: İcra olunur")
        Notification.objects.get_or_create(user=portal_user, message="TK-1038 həll edildi")
        Notification.objects.get_or_create(user=portal_user, ticket=t1042, message="Yeni cavab: texniki komanda")

        Announcement.objects.update_or_create(
            title="Yeni Lift texniki xidmət",
            defaults={
                "body": "21 avqust saat 22:00-02:00 arası A liftində planlı texniki iş aparılacaq.",
                "severity": AnnouncementSeverity.UPDATE,
                "published_at": date(2026, 8, 18),
            },
        )
        Announcement.objects.update_or_create(
            title="Parkinq yenilənməsi",
            defaults={
                "body": "B2 mərtəbəsində qonaq park yerləri yenidən nömrələnib. Xəritə Documents bölməsindədir.",
                "severity": AnnouncementSeverity.INFO,
                "published_at": date(2026, 8, 15),
            },
        )
        Announcement.objects.update_or_create(
            title="Yanğın təlimi",
            defaults={
                "body": "27 avqust saat 11:00-da evakuasiya təlimi keçiriləcək. Bütün rezidentlər məlumatlandırılır.",
                "severity": AnnouncementSeverity.IMPORTANT,
                "published_at": date(2026, 8, 10),
            },
        )

        docs = [
            ("İcarə müqaviləsi - 801", "PDF", "2.4 MB", asbc, space801, date(2025, 1, 12)),
            ("Əlavə razılaşma №2", "PDF", "480 KB", asbc, space801, date(2026, 6, 3)),
            ("Mərtəbə planı F08 - Rev.04", "DWG", "8.1 MB", asbc, space801, date(2026, 8, 1)),
            ("Yanğın təhlükəsizliyi təlimatı", "PDF", "1.1 MB", asbc, None, date(2026, 3, 20)),
            ("Parkinq qaydaları", "PDF", "320 KB", None, None, date(2026, 8, 15)),
        ]
        for title, ftype, size, company, space, pub in docs:
            Document.objects.update_or_create(
                title=title,
                defaults={
                    "file_type": ftype,
                    "size_label": size,
                    "company": company,
                    "space": space,
                    "published_at": pub,
                    "version": "Rev.04" if "planı" in title else "",
                },
            )

        self.stdout.write(self.style.SUCCESS("Demo data hazırdır."))
        from decimal import Decimal

        from apps.accounting.models import Account, AccountType
        from apps.billing.models import Charge, ChargeSource, Invoice, InvoiceLine, InvoiceStatus
        from apps.billing.services import generate_invoice_from_charges
        from apps.crm.models import Lead, LeadSource, LeadStatus, Offer, OfferStatus, Opportunity, OpportunityStatus
        from apps.crm.services import convert_offer_to_lease_draft
        from apps.leases.models import Lease, LeaseStatus
        from apps.leases.services import activate_lease, next_lease_code
        from apps.parties.services import PartyService
        from apps.procurement.models import POStatus, PRStatus, PurchaseOrder, PurchaseRequest
        from apps.property.models import ParkingSpot, ParkingZone, UtilityMeter, UtilityType
        from apps.rbac.services import seed_rbac_catalog
        from apps.warehouse.models import SKU, StockMovementType, Warehouse
        from apps.warehouse.services import apply_movement

        sync = PartyService.sync_all_from_legacy()
        perms = seed_rbac_catalog()

        asbc_party = asbc.party
        zone, _ = ParkingZone.objects.get_or_create(
            code="P1", defaults={"name": "Parking Level 1", "building": building}
        )
        spot, _ = ParkingSpot.objects.get_or_create(zone=zone, code="A-12")
        UtilityMeter.objects.get_or_create(
            space=space801, meter_code="EL-801", defaults={"utility_type": UtilityType.ELECTRIC, "unit": "kWh"}
        )

        Lead.objects.update_or_create(
            external_id="seed-lead-502",
            defaults={
                "full_name": "Elnur Məmmədov",
                "email": "elnur@example.az",
                "phone": "+994501112233",
                "company_name": "Nova Soft",
                "source": LeadSource.WEBSITE,
                "status": LeadStatus.QUALIFIED,
                "message": "Interested in floor 5 office",
                "interested_space": vacant_office,
            },
        )
        lead = Lead.objects.get(external_id="seed-lead-502")
        opp, _ = Opportunity.objects.update_or_create(
            title="Nova Soft F05",
            defaults={
                "lead": lead,
                "party": asbc_party,
                "status": OpportunityStatus.OPEN,
                "expected_area": Decimal("96"),
                "notes": "Seed opportunity",
            },
        )
        # Prospect party for offer
        from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType

        nova, _ = Party.objects.update_or_create(
            legal_name="Nova Soft MMC",
            defaults={
                "party_type": PartyType.ORGANIZATION,
                "brand_name": "Nova Soft",
                "status": PartyStatus.PROSPECT,
                "contact_email": "elnur@example.az",
            },
        )
        PartyRole.objects.get_or_create(party=nova, role=PartyRoleCode.PROSPECT, defaults={"is_primary": True})
        offer, _ = Offer.objects.update_or_create(
            opportunity=opp,
            party=nova,
            space=vacant_office,
            defaults={
                "status": OfferStatus.SENT,
                "rent_amount": Decimal("2500.00"),
                "notes": "Seed offer for 502",
            },
        )
        if not offer.lease_id:
            convert_offer_to_lease_draft(offer)
            offer.refresh_from_db()

        lease_asbc, created_lease = Lease.objects.update_or_create(
            code="LS-1001",
            defaults={
                "party": asbc_party,
                "space": space801,
                "status": LeaseStatus.SIGNED,
                "start_date": date(2025, 1, 1),
                "end_date": date(2027, 12, 31),
                "rent": Decimal("4500.00"),
                "deposit": Decimal("9000.00"),
                "service_charge": Decimal("600.00"),
                "notes": "ASBC primary lease",
            },
        )
        if lease_asbc.status != LeaseStatus.ACTIVE:
            activate_lease(lease_asbc)

        wh, _ = Warehouse.objects.get_or_create(code="MAIN", defaults={"name": "Main store"})
        sku_filter, _ = SKU.objects.get_or_create(
            code="FLT-HVAC", defaults={"name": "HVAC Filter", "unit": "pcs", "reorder_level": Decimal("5")}
        )
        if not sku_filter.stocks.filter(warehouse=wh).exists():
            apply_movement(
                sku=sku_filter,
                warehouse=wh,
                movement_type=StockMovementType.RECEIPT,
                quantity=Decimal("20"),
                reference="SEED",
            )

        PurchaseRequest.objects.get_or_create(
            code="PR-1001",
            defaults={"title": "HVAC filters restock", "status": PRStatus.SUBMITTED, "source": "low_stock"},
        )
        PurchaseOrder.objects.get_or_create(
            code="PO-1001",
            defaults={"supplier_party": nova, "status": POStatus.SENT, "notes": "Seed PO"},
        )

        if not Charge.objects.filter(party=asbc_party, description="Seed rent Sep").exists():
            Charge.objects.create(
                party=asbc_party,
                lease=lease_asbc,
                space=space801,
                source=ChargeSource.RENT,
                description="Seed rent Sep",
                amount=Decimal("4500.00"),
                period_start=date(2026, 9, 1),
                period_end=date(2026, 9, 30),
            )
            Charge.objects.create(
                party=asbc_party,
                lease=lease_asbc,
                space=space801,
                source=ChargeSource.SERVICE_CHARGE,
                description="Seed SC Sep",
                amount=Decimal("600.00"),
                period_start=date(2026, 9, 1),
                period_end=date(2026, 9, 30),
            )
        if not Invoice.objects.filter(party=asbc_party).exists():
            charge_ids = list(
                Charge.objects.filter(party=asbc_party, invoice__isnull=True).values_list("id", flat=True)
            )
            if charge_ids:
                generate_invoice_from_charges(asbc_party, charge_ids)

        Account.objects.get_or_create(code="1000", defaults={"name": "Cash", "account_type": AccountType.ASSET})
        Account.objects.get_or_create(code="1100", defaults={"name": "AR", "account_type": AccountType.ASSET})
        Account.objects.get_or_create(code="4000", defaults={"name": "Rent Revenue", "account_type": AccountType.REVENUE})
        Account.objects.get_or_create(
            code="4100", defaults={"name": "Service Charge Revenue", "account_type": AccountType.REVENUE}
        )

        self.stdout.write(f"Scope sync: parties={sync['parties']} people={sync['people']} rbac_new={perms}")
        self.stdout.write("Portal: office@asbc.az / asbc123")
        self.stdout.write("ERP admin: admin@citypoint.az / admin123")
        self.stdout.write("Reception: reception@citypoint.az / reception123")
        self.stdout.write("Service Desk: desk@citypoint.az / desk123")
        self.stdout.write("Security: security@citypoint.az / security123 → /security/")
