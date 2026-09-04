from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.timezone import make_aware

from apps.accounts.models import Role, User
from apps.comms.models import Announcement, AnnouncementSeverity, Notification
from apps.documents.models import Document
from apps.property.models import Asset, Building, Contractor, Floor, Occupancy, Space
from apps.reception.models import Guest, GuestVisit, VisitStatus
from apps.residents.models import AccessEvent, AccessEventType, ResidentCompany, ResidentEmployee
from apps.tickets.models import (
    SlaPolicy,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketPriority,
    TicketStatus,
)


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
                "cost_center": "CC-F08-801",
                "plan_revision": "Rev.04",
            },
        )
        lobby, _ = Space.objects.update_or_create(
            code="CP-F01-LOB-001",
            defaults={"name": "Lobby", "floor": f01, "area_m2": "240.0", "access_zone": "F01"},
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
        for full_name, card in [
            ("N. Həsənov", "AC-1042"),
            ("S. Quliyeva", "AC-1108"),
            ("R. Əliyev", "AC-1091"),
            ("L. Məmmədova", "AC-1077"),
            ("K. Orucov", "AC-1120"),
        ]:
            emp, _ = ResidentEmployee.objects.update_or_create(
                company=asbc, card_number=card, defaults={"full_name": full_name, "is_active": True}
            )
            employees[full_name] = emp
        tech_host, _ = ResidentEmployee.objects.update_or_create(
            company=techco, card_number="AC-2201", defaults={"full_name": "R. Quliyev"}
        )

        today = timezone.localdate()
        tz = timezone.get_current_timezone()

        def at_hour(h, m=0):
            return make_aware(datetime.combine(today, time(h, m)), tz)

        if not AccessEvent.objects.filter(employee__company=asbc, occurred_at__date=today).exists():
            AccessEvent.objects.bulk_create(
                [
                    AccessEvent(employee=employees["N. Həsənov"], event_type=AccessEventType.IN, occurred_at=at_hour(8, 52)),
                    AccessEvent(employee=employees["S. Quliyeva"], event_type=AccessEventType.IN, occurred_at=at_hour(9, 5)),
                    AccessEvent(employee=employees["R. Əliyev"], event_type=AccessEventType.IN, occurred_at=at_hour(8, 40)),
                    AccessEvent(employee=employees["R. Əliyev"], event_type=AccessEventType.OUT, occurred_at=at_hour(13, 10)),
                    AccessEvent(employee=employees["L. Məmmədova"], event_type=AccessEventType.IN, occurred_at=at_hour(9, 18)),
                    AccessEvent(employee=employees["K. Orucov"], event_type=AccessEventType.IN, occurred_at=at_hour(8, 30)),
                    AccessEvent(employee=employees["K. Orucov"], event_type=AccessEventType.OUT, occurred_at=at_hour(12, 45)),
                ]
            )

        if not GuestVisit.objects.filter(scheduled_for=today).exists():
            guest_rows = [
                ("A. Məmmədov", asbc, employees["N. Həsənov"], f08, space801, VisitStatus.INSIDE, at_hour(10, 15), None),
                ("L. Əliyeva", techco, tech_host, f05, None, VisitStatus.WAITING, None, None),
                ("K. Orucov", asbc, employees["N. Həsənov"], f08, space801, VisitStatus.LEFT, at_hour(9, 40), at_hour(11, 10)),
                ("T. Hüseynov", asbc, employees["N. Həsənov"], f08, space801, VisitStatus.LEFT, at_hour(9, 40), at_hour(10, 5)),
                ("M. Rəhimova", asbc, employees["R. Əliyev"], None, None, VisitStatus.WAITING, None, None),
            ]
            for name, company, host, floor, space, status, cin, cout in guest_rows:
                guest, _ = Guest.objects.get_or_create(full_name=name)
                GuestVisit.objects.create(
                    guest=guest,
                    company=company,
                    host=host,
                    floor=floor,
                    space=space,
                    location_note="Meeting R." if name == "M. Rəhimova" else "",
                    status=status,
                    scheduled_for=today,
                    check_in_at=cin,
                    check_out_at=cout,
                )

        cats = {}
        for slug, name in [
            ("hvac", "HVAC / Kondisioner"),
            ("access", "Access Card"),
            ("cleaning", "Təmizlik"),
            ("electric", "Elektrik"),
        ]:
            cats[slug], _ = TicketCategory.objects.get_or_create(slug=slug, defaults={"name": name})

        for prio, hours, label in [
            (TicketPriority.HIGH, 8, "Yüksək SLA"),
            (TicketPriority.NORMAL, 24, "Normal SLA"),
            (TicketPriority.LOW, 48, "Aşağı SLA"),
        ]:
            SlaPolicy.objects.update_or_create(priority=prio, defaults={"name": label, "hours": hours})

        staff_map = {
            "admin": ("admin@citypoint.az", "Admin", Role.ADMIN, "admin123"),
            "reception": ("reception@citypoint.az", "Reception", Role.RECEPTION, "reception123"),
            "desk": ("desk@citypoint.az", "Service Desk", Role.SERVICE_DESK, "desk123"),
            "fm": ("fm@citypoint.az", "Property FM", Role.PROPERTY_FM, "fm123"),
            "manager": ("manager@citypoint.az", "Rəhbərlik", Role.MANAGEMENT, "manager123"),
        }
        created_users = {}
        for uname, (email, first, role, password) in staff_map.items():
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
        now = timezone.now()

        def upsert_ticket(code, cat, company, space, prio, status, desc, sla_hours):
            ticket, _ = Ticket.objects.update_or_create(
                code=code,
                defaults={
                    "category": cat,
                    "company": company,
                    "space": space,
                    "requester": portal_user if company == asbc else None,
                    "assignee": desk if status in {TicketStatus.IN_PROGRESS, TicketStatus.ACCEPTED} else None,
                    "priority": prio,
                    "status": status,
                    "description": desc,
                    "sla_due_at": now + timedelta(hours=sla_hours),
                },
            )
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
            cats["hvac"],
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
        upsert_ticket("TK-1040", cats["electric"], asbc, None, TicketPriority.NORMAL, TicketStatus.SENT, "Koridor F03 işıqları yanıb-sönür.", 24)
        upsert_ticket("TK-1038", cats["access"], asbc, space801, TicketPriority.NORMAL, TicketStatus.RESOLVED, "Access kart yenilənməsi.", 24)
        upsert_ticket("TK-1035", cats["access"], techco, None, TicketPriority.NORMAL, TicketStatus.ACCEPTED, "Yeni əməkdaş üçün kart.", 24)
        upsert_ticket("TK-1031", cats["cleaning"], asbc, lobby, TicketPriority.LOW, TicketStatus.IN_PROGRESS, "F01 Lobby təmizlik.", 48)
        upsert_ticket("TK-1021", cats["cleaning"], asbc, space801, TicketPriority.NORMAL, TicketStatus.RESOLVED, "Ofis təmizliyi.", 24)
        upsert_ticket("TK-1010", cats["electric"], asbc, space801, TicketPriority.NORMAL, TicketStatus.RESOLVED, "Rozetka nasazlığı.", 24)

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
        self.stdout.write("Portal: office@asbc.az / asbc123")
        self.stdout.write("ERP admin: admin@citypoint.az / admin123")
        self.stdout.write("Reception: reception@citypoint.az / reception123")
        self.stdout.write("Service Desk: desk@citypoint.az / desk123")
