"""M12 acceptance — flow smoke, resilience, demo/prod guard, AxTrax dedupe."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.billing.models import Charge, ChargeSource, InvoiceStatus
from apps.billing.services import confirm_invoice, generate_invoice_from_charges, record_payment
from apps.comms.models import NotificationChannel, NotificationDispatch
from apps.comms.services import flush_pending_email_dispatches
from apps.documents.validation import validate_document_file
from apps.leases.lease_ops import LeaseService
from apps.leases.models import LeaseStatus
from apps.leases.services import activate_lease
from apps.maintenance.models import WorkOrder
from apps.parties.resolvers import party_for_company
from apps.procurement.services import ProcurementService
from apps.property.models import Building, Floor, Occupancy, Space
from apps.reception.models import GuestVisit
from apps.reception.services import pre_register_visit
from apps.residents.models import AccessEvent, ResidentCompany, ResidentEmployee
from apps.tickets.models import TicketCategory, TicketSubcategory, TicketType
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import create_ticket_from_portal, create_work_order_from_ticket
from apps.warehouse.models import SKU, Stock, Warehouse

User = get_user_model()


class M12FlowAcceptanceTests(TestCase):
    """Thin e2e of PRODUCT_DELIVERY flows (local/mock)."""

    def setUp(self):
        seed_ticket_taxonomy()
        self.company = ResidentCompany.objects.create(
            name="M12 Co", slug="m12-co", portal_active=True, status="active", is_internal=False
        )
        self.party = party_for_company(self.company, ensure=True)
        building = Building.objects.create(code="M12B", name="M12B")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.space = Space.objects.create(
            code="M12-S1",
            name="S1",
            floor=floor,
            area_m2=Decimal("50"),
            rentable_area_m2=Decimal("50"),
            occupancy=Occupancy.VACANT,
            base_rent_rate=Decimal("10"),
            service_charge_rate=Decimal("2"),
        )
        self.resident = User.objects.create_user(
            username="m12-res",
            email="m12-res@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        ensure_portal_membership(self.resident, self.company)
        from apps.tickets.models import TicketDepartment

        desk_dept = TicketDepartment.objects.get(code="servicedesk")
        self.staff = User.objects.create_user(
            username="m12-desk",
            email="m12-desk@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=desk_dept,
        )

    def test_flow_lease_billing_gl(self):
        lease = LeaseService.create_draft(
            party=self.party,
            space=self.space,
            start_date=date(2026, 11, 1),
            end_date=date(2027, 10, 31),
            rent_rate_per_m2=Decimal("10"),
            service_rate_per_m2=Decimal("2"),
        )
        activate_lease(lease, actor=self.staff)
        lease.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.ACTIVE)
        charge = Charge.objects.create(
            party=self.party,
            lease=lease,
            source=ChargeSource.RENT,
            description="M12 rent",
            amount=Decimal("100.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        record_payment(invoice=inv, amount=inv.total, method="bank", reference="M12")
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.PAID)

    def test_flow_ticket_wo(self):
        ticket = create_ticket_from_portal(
            company=self.company,
            requester=self.resident,
            ticket_type=TicketType.INCIDENT,
            category=TicketCategory.objects.get(slug="technical"),
            subcategory=TicketSubcategory.objects.get(slug="hvac"),
            description="M12 technical flow",
        )
        wo = create_work_order_from_ticket(ticket, actor=self.staff)
        self.assertTrue(WorkOrder.objects.filter(pk=wo.pk, ticket=ticket).exists())

    def test_flow_guest_reception(self):
        host = ResidentEmployee.objects.create(
            company=self.company,
            full_name="Host M12",
            is_active=True,
        )
        visit = pre_register_visit(
            company=self.company,
            full_name="Guest M12",
            host=host,
            scheduled_for=timezone.localdate(),
            portal_user=self.resident,
        )
        self.assertTrue(GuestVisit.objects.filter(pk=visit.pk).exists())

    def test_flow_procurement_low_stock_dedupe(self):
        wh, _ = Warehouse.objects.get_or_create(code="M12W", defaults={"name": "M12 WH"})
        sku, _ = SKU.objects.get_or_create(
            code="M12-SKU",
            defaults={"name": "Bolt", "unit": "pcs", "reorder_level": Decimal("10")},
        )
        stock, _ = Stock.objects.get_or_create(
            warehouse=wh, sku=sku, defaults={"quantity": Decimal("2")}
        )
        stock.quantity = Decimal("2")
        stock.save(update_fields=["quantity"])
        pr1 = ProcurementService.create_pr_from_low_stock(stock=stock, requested_by=self.staff)
        pr2 = ProcurementService.create_pr_from_low_stock(stock=stock, requested_by=self.staff)
        self.assertEqual(pr1.pk, pr2.pk)


class M12ResilienceTests(TestCase):
    def test_email_outbox_failure_keeps_retry(self):
        NotificationDispatch.objects.create(
            channel=NotificationChannel.EMAIL,
            status="pending",
            recipient="fail@test.az",
            template_code="ticket.department",
            payload={"subject": "x", "message": "y"},
        )
        with patch("apps.comms.services.send_mail", side_effect=OSError("down")):
            stats = flush_pending_email_dispatches(template_prefix="ticket.", limit=5)
        self.assertEqual(stats["failed"], 1)
        row = NotificationDispatch.objects.get(recipient="fail@test.az")
        self.assertEqual(row.status, "pending")
        self.assertIsNotNone(row.next_retry_at)

    def test_invalid_document_file_rejected(self):
        bad = SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream")
        with self.assertRaises(Exception):
            validate_document_file(bad)

    def test_seed_demo_blocked_in_production(self):
        with override_settings(CP_ENV="production"):
            with self.assertRaises(CommandError):
                call_command("seed_demo")


class M12AxtraxDedupeTests(TestCase):
    def test_duplicate_event_external_id_skipped(self):
        from apps.integrations.axtrax_events_sync import sync_event_rows
        from apps.integrations.axtrax_people_sync import AXTRAX_SYSTEM
        from apps.integrations.models import ExternalIdentity, SyncStatus

        company = ResidentCompany.objects.create(name="Ax M12", slug="ax-m12", portal_active=True)
        emp = ResidentEmployee.objects.create(company=company, full_name="Emp", is_active=True)
        ExternalIdentity.objects.create(
            system=AXTRAX_SYSTEM,
            external_id="emp:99",
            entity_type=ContentType.objects.get_for_model(ResidentEmployee),
            entity_id=emp.pk,
            last_sync_at=timezone.now(),
            last_status=SyncStatus.SUCCESS,
        )
        row = {
            "event_id": 9001,
            "employee_id": 99,
            "event_type": 1,
            "occurred_at": timezone.now(),
            "reader_out": 0,
            "reader_id": 1,
            "reader_name": "Gate",
            "badge_number": "1",
            "full_name": "Emp",
        }
        s1 = sync_event_rows([row], since_id=0, advance_cursor=False, detect_alerts=False)
        s2 = sync_event_rows([row], since_id=0, advance_cursor=False, detect_alerts=False)
        self.assertEqual(s1.get("created", 0), 1)
        self.assertGreaterEqual(s2.get("skipped_existing", 0), 1)
        self.assertEqual(AccessEvent.objects.filter(axtrax_employee_id=99).count(), 1)
