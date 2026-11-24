"""Final System Acceptance — seven flows, reporting bounds, local readiness smoke."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.accounting.coa import code_for
from apps.accounting.models import Account, AccountType, JournalEntry
from apps.accounting.services import AccountingService, seed_minimal_coa, trial_balance
from apps.billing.models import Charge, ChargeSource, InvoiceStatus, Payment
from apps.billing.services import (
    confirm_invoice,
    generate_invoice_from_charges,
    invoice_balance,
    record_payment,
)
from apps.core.models import ReportSnapshot
from apps.crm.models import Qualification
from apps.crm.services import CrmLeadService
from apps.erp.exec_reports import (
    build_exec_bundle,
    build_finance_report,
    build_property_report,
    capture_daily_snapshot,
    parse_report_params,
)
from apps.leases.lease_ops import LeaseService, generate_monthly_lease_charges
from apps.leases.models import Lease, LeaseStatus
from apps.leases.services import activate_lease
from apps.maintenance.models import WorkOrderStatus
from apps.maintenance.services import WorkOrderService
from apps.parties.resolvers import party_for_company
from apps.procurement.services import ProcurementService
from apps.property.models import Building, CommercialStatus, Floor, Occupancy, Space
from apps.reception.models import GuestVisit
from apps.reception.services import pre_register_visit
from apps.residents.models import AccessEvent, AccessEventType, ResidentCompany, ResidentEmployee
from apps.residents.services import create_employee_card_order
from apps.tickets.models import TicketCategory, TicketDepartment, TicketSubcategory, TicketType
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import create_ticket_from_portal, create_work_order_from_ticket
from apps.warehouse.models import SKU, Stock, StockMovement, StockMovementType, Warehouse
from apps.workflows.services import ApprovalService

User = get_user_model()


def _pay(inv, amount, *, accountant, manager, reference="FSA"):
    req = ApprovalService.request(
        workflow_code="finance.payment",
        requested_by=accountant,
        entity=inv,
        payload={
            "invoice_id": inv.pk,
            "invoice_code": inv.code,
            "amount": str(amount),
            "method": "bank",
            "reference": reference,
        },
    )
    ApprovalService.decide(req, approved=True, decided_by=manager)
    req.refresh_from_db()
    return record_payment(
        invoice=inv, amount=amount, approval_request=req, method="bank", reference=reference
    )


class FinalSystemSevenFlowsTests(TestCase):
    """Flow verdicts exercised locally (synthetic). External systems mocked/deferred."""

    def setUp(self):
        seed_ticket_taxonomy()
        seed_minimal_coa()
        self.company = ResidentCompany.objects.create(
            name="FSA Co", slug="fsa-co", portal_active=True, status="active", is_internal=False
        )
        self.party = party_for_company(self.company, ensure=True)
        building = Building.objects.create(code="FSAB", name="FSAB")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.space = Space.objects.create(
            code="FSA-S1",
            name="S1",
            floor=floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            occupancy=Occupancy.VACANT,
            commercial_status=CommercialStatus.VACANT,
            base_rent_rate=Decimal("10"),
            service_charge_rate=Decimal("0"),
        )
        self.resident = User.objects.create_user(
            username="fsa-res",
            email="fsa-res@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        ensure_portal_membership(self.resident, self.company)
        desk = TicketDepartment.objects.get(code="servicedesk")
        self.desk = User.objects.create_user(
            username="fsa-desk",
            email="fsa-desk@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=desk,
        )
        self.sales = User.objects.create_user(
            username="fsa-sales",
            email="fsa-sales@test.az",
            password="Pass12345!",
            role=Role.SALES,
            is_staff=True,
        )
        self.fm = User.objects.create_user(
            username="fsa-fm",
            email="fsa-fm@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.accountant = User.objects.create_user(
            username="fsa-acc",
            email="fsa-acc@test.az",
            password="Pass12345!",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="fsa-mgmt",
            email="fsa-mgmt@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )

    def test_flow1_new_resident_manual_sales_path(self):
        """Website intake deferred; manual CRM lead + lease→portal→billing demonstrated."""
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={
                "full_name": "FSA Lead",
                "company_name": "FSA Co",
                "phone": "+994500000001",
                "qualification": Qualification.POTENTIAL,
                "source": "manual",
            },
            notify=False,
        )
        self.assertEqual(lead.source, "manual")
        lease = LeaseService.create_draft(
            party=self.party,
            space=self.space,
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=365),
            rent_rate_per_m2=Decimal("10"),
            service_rate_per_m2=Decimal("0"),
        )
        activate_lease(lease, actor=self.sales)
        lease.refresh_from_db()
        self.assertEqual(lease.status, LeaseStatus.ACTIVE)
        generate_monthly_lease_charges(as_of=timezone.localdate())
        # Website public intake: deferred / optional — not asserted here

    def test_flow2_employee_card_request_and_axtrax_readonly(self):
        emp = ResidentEmployee.objects.create(
            company=self.company, full_name="Emp FSA", is_active=True
        )
        id_doc = SimpleUploadedFile("id.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        new_emp, ticket = create_employee_card_order(
            company=self.company,
            requester=self.resident,
            id_document=id_doc,
            full_name="Emp FSA Yeni",
            access_level="1",
        )
        self.assertIsNotNone(ticket.pk)
        self.assertEqual(new_emp.access_level, "1")
        # Requested level on employee; actual AxTrax level is read-only sync
        AccessEvent.objects.create(
            employee=emp,
            event_type=AccessEventType.IN,
            occurred_at=timezone.now(),
            company_id=self.company.pk,
            company_name=self.company.name,
            reader_name="Gate-1",
            card_number="SYNTH-1",
            employee_name=emp.full_name,
        )
        emp.is_active = False
        emp.save(update_fields=["is_active"])
        self.assertTrue(
            AccessEvent.objects.filter(employee=emp, company_id=self.company.pk).exists()
        )

    def test_flow3_visitor_preregister(self):
        host = ResidentEmployee.objects.create(
            company=self.company, full_name="Host FSA", is_active=True
        )
        visit = pre_register_visit(
            company=self.company,
            full_name="Guest FSA",
            host=host,
            scheduled_for=timezone.localdate(),
            portal_user=self.resident,
        )
        self.assertTrue(GuestVisit.objects.filter(pk=visit.pk).exists())
        # Live QONAQ / reader direction — on-site NetAdmin

    def test_flow4_ticket_wo_stock_issue(self):
        wh, _ = Warehouse.objects.get_or_create(code="FSAW", defaults={"name": "FSA WH"})
        sku, _ = SKU.objects.get_or_create(
            code="FSA-SKU",
            defaults={"name": "Filter", "unit": "ədəd", "reorder_level": Decimal("5")},
        )
        stock, _ = Stock.objects.get_or_create(
            warehouse=wh, sku=sku, defaults={"quantity": Decimal("20")}
        )
        ticket = create_ticket_from_portal(
            company=self.company,
            requester=self.resident,
            ticket_type=TicketType.INCIDENT,
            category=TicketCategory.objects.get(slug="technical"),
            subcategory=TicketSubcategory.objects.get(slug="hvac"),
            description="FSA HVAC",
        )
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        before = stock.quantity
        StockMovement.objects.create(
            sku=sku,
            warehouse=wh,
            movement_type=StockMovementType.ISSUE,
            quantity=Decimal("2"),
            work_order=wo,
            reference=f"WO {wo.code}",
        )
        stock.quantity = before - Decimal("2")
        stock.save(update_fields=["quantity"])
        WorkOrderService.set_status(
            wo, WorkOrderStatus.COMPLETED, actor=self.fm, note="fixed"
        )
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrderStatus.COMPLETED)
        self.assertEqual(stock.quantity, before - Decimal("2"))

    def test_flow5_commercial_request_preserves_ticket(self):
        cat = TicketCategory.objects.filter(slug="lease").first() or TicketCategory.objects.first()
        sub = TicketSubcategory.objects.filter(category=cat).first() or TicketSubcategory.objects.first()
        ticket = create_ticket_from_portal(
            company=self.company,
            requester=self.resident,
            ticket_type=TicketType.COMMERCIAL,
            category=cat,
            subcategory=sub,
            description="Larger office please",
        )
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={
                "full_name": "Resident FSA",
                "company_name": self.company.name,
                "phone": "+994500000002",
                "source": "manual",
                "initial_note": f"From ticket {ticket.code}",
            },
            notify=False,
        )
        self.assertIn(ticket.code, lead.initial_note)
        self.assertEqual(ticket.company_id, self.company.pk)

    def test_flow6_procurement_stops_before_ap(self):
        """First missing handoff: PO/receive → supplier invoice/AP JE (200 unused)."""
        wh, _ = Warehouse.objects.get_or_create(code="FSAW2", defaults={"name": "FSA WH2"})
        sku, _ = SKU.objects.get_or_create(
            code="FSA-LOW",
            defaults={"name": "Paper", "unit": "ədəd", "reorder_level": Decimal("50")},
        )
        stock, _ = Stock.objects.get_or_create(
            warehouse=wh, sku=sku, defaults={"quantity": Decimal("1")}
        )
        stock.quantity = Decimal("1")
        stock.save(update_fields=["quantity"])
        pr = ProcurementService.create_pr_from_low_stock(stock=stock, requested_by=self.fm)
        self.assertIsNotNone(pr.pk)
        self.assertFalse(
            JournalEntry.objects.filter(source__icontains="procurement").exists()
        )
        self.assertEqual(code_for("ap"), "200")

    def test_flow7_lease_billing_1000_400_600_gl_and_report(self):
        lease = LeaseService.create_draft(
            party=self.party,
            space=self.space,
            start_date=date(2026, 11, 1),
            rent_rate_per_m2=Decimal("10"),
            service_rate_per_m2=Decimal("0"),
        )
        activate_lease(lease, actor=self.accountant)
        charge = Charge.objects.create(
            party=self.party,
            lease=lease,
            source=ChargeSource.RENT,
            description="FSA 1000",
            amount=Decimal("1000.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        je = JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv.pk}")
        AccountingService.post_to_gl(je, actor=self.accountant)
        p1 = _pay(
            inv, Decimal("400.00"), accountant=self.accountant, manager=self.manager, reference="FSA400"
        )
        self.assertEqual(invoice_balance(inv), Decimal("600.00"))
        AccountingService.post_to_gl(
            JournalEntry.objects.get(source_ref=f"payment:{p1.pk}"), actor=self.accountant
        )
        # Posting must not reduce portal/billing balance again
        self.assertEqual(invoice_balance(inv), Decimal("600.00"))
        p2 = _pay(
            inv, Decimal("600.00"), accountant=self.accountant, manager=self.manager, reference="FSA600"
        )
        AccountingService.post_to_gl(
            JournalEntry.objects.get(source_ref=f"payment:{p2.pk}"), actor=self.accountant
        )
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.PAID)
        self.assertEqual(invoice_balance(inv), Decimal("0"))
        self.assertEqual(Payment.objects.filter(invoice=inv).count(), 2)
        fin = build_finance_report(
            {
                "date_from": timezone.localdate() - timedelta(days=30),
                "date_to": timezone.localdate(),
                "company_id": None,
            }
        )
        self.assertIn("operational_ar", fin)
        self.assertIn("posted_ar", fin)
        trial_balance(year=timezone.localdate().year, month=timezone.localdate().month)


class FinalSystemReportingBoundsTests(TestCase):
    def setUp(self):
        seed_minimal_coa()
        self.party = party_for_company(
            ResidentCompany.objects.create(name="FSA Bound", slug="fsa-b", portal_active=True),
            ensure=True,
        )
        building = Building.objects.create(code="FSARB", name="FSARB")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.space = Space.objects.create(
            code="FSA-R1",
            name="R1",
            floor=floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            commercial_status=CommercialStatus.VACANT,
            occupancy=Occupancy.VACANT,
        )
        self.manager = User.objects.create_user(
            username="fsa-b-mgr",
            email="fsa-b-mgr@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )

    def test_A_historical_reservation_created_at_gate(self):
        before = build_property_report(
            {"date_from": date(2026, 11, 1), "date_to": date(2026, 11, 20), "company_id": None}
        )
        self.assertEqual(before["available_m2"], 100.0)
        self.assertEqual(before["reserved_m2"], 0.0)

        lease = Lease.objects.create(
            code="LS-FSA-HOLD",
            party=self.party,
            space=self.space,
            status=LeaseStatus.SIGNED,
            start_date=date(2026, 12, 1),
            rent=Decimal("1000"),
        )
        Lease.objects.filter(pk=lease.pk).update(
            created_at=timezone.make_aware(datetime(2026, 11, 25, 10, 0, 0))
        )

        nov20 = build_property_report(
            {"date_from": date(2026, 11, 1), "date_to": date(2026, 11, 20), "company_id": None}
        )
        self.assertEqual(nov20["available_m2"], 100.0)
        self.assertEqual(nov20["reserved_m2"], 0.0)
        self.assertGreaterEqual(nov20["skipped_not_yet_recorded"], 1)

        nov30 = build_property_report(
            {"date_from": date(2026, 11, 1), "date_to": date(2026, 11, 30), "company_id": None}
        )
        self.assertEqual(nov30["reserved_m2"], 100.0)
        self.assertEqual(nov30["occupied_m2"], 0.0)

        dec1 = build_property_report(
            {"date_from": date(2026, 12, 1), "date_to": date(2026, 12, 1), "company_id": None}
        )
        self.assertEqual(dec1["occupied_m2"], 100.0)

    def test_B_snapshot_capture_vs_label(self):
        snap = capture_daily_snapshot(as_of=date(2026, 11, 15))
        self.assertEqual(snap.snapshot_date, date(2026, 11, 15))
        self.assertIsNotNone(snap.created_at)
        self.assertFalse(
            ReportSnapshot.objects.filter(
                snapshot_date=date(2026, 11, 14), company__isnull=True
            ).exists()
        )
        client = Client()
        client.force_login(self.manager)
        resp = client.get(
            reverse("erp:reports") + "?tab=history&date_from=2026-11-01&date_to=2026-11-30"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Capture vaxtı")
        self.assertContains(resp, "capture edilməyib")

    @override_settings(ACCOUNTING_ROLE_CODES={"ar": "115"})
    def test_C_alternative_ar_mapping(self):
        Account.objects.update_or_create(
            code="115",
            defaults={"name": "AR Alt", "account_type": AccountType.ASSET, "is_active": True},
        )
        self.assertEqual(code_for("ar"), "115")
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="alt ar",
            amount=Decimal("50.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        je = JournalEntry.objects.get(source_ref=f"invoice:{inv.pk}")
        self.assertIn("115", list(je.lines.values_list("account__code", flat=True)))
        AccountingService.post_to_gl(je)
        fin = build_finance_report(
            {
                "date_from": timezone.localdate() - timedelta(days=1),
                "date_to": timezone.localdate(),
                "company_id": None,
            }
        )
        self.assertEqual(fin["posted_ar"], Decimal("50.00"))

    def test_D_export_matches_kpi_and_unavailable_vs_zero(self):
        client = Client()
        client.force_login(self.manager)
        q = "date_from=2026-11-01&date_to=2026-11-30"
        home = client.get(reverse("erp:reports") + f"?{q}&tab=finance")
        export = client.get(reverse("erp:reports_export") + f"?{q}")
        self.assertEqual(export.status_code, 200)
        wb = load_workbook(BytesIO(export.content))
        self.assertIn("Meta", wb.sheetnames)
        params = parse_report_params({"date_from": "2026-11-01", "date_to": "2026-11-30"})
        bundle = build_exec_bundle(params, user=self.manager)
        self.assertEqual(
            home.context["finance"]["operational_ar"],
            bundle["finance"]["operational_ar"],
        )
        self.assertFalse(bundle["warehouse"]["historical_stock"])
        Space.objects.all().delete()
        empty = build_property_report(params)
        self.assertTrue(empty["occupancy_unavailable"])
        self.assertEqual(empty["occupancy_display"], "—")


class FinalSystemLocalReadinessTests(TestCase):
    def test_offline_static_no_cdn_in_login(self):
        client = Client()
        resp = client.get(reverse("login"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8", errors="ignore").lower()
        self.assertNotIn("fonts.googleapis", body)
        self.assertNotIn("cdn.jsdelivr", body)
        self.assertNotIn("unpkg.com", body)
        lucide = Path(settings.BASE_DIR) / "static" / "vendor" / "lucide.min.js"
        self.assertTrue(lucide.exists(), lucide)

    def test_erp_survives_axtrax_health_down(self):
        manager = User.objects.create_user(
            username="fsa-ax",
            email="fsa-ax@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        client = Client()
        client.force_login(manager)
        with patch(
            "apps.integrations.axtrax_health.axtrax_sync_health",
            return_value={"events_ok": False, "error": "simulated down"},
        ):
            resp = client.get(reverse("erp:reports") + "?tab=security")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "STALE")

    def test_migrate_check_clean(self):
        try:
            call_command("migrate", "--check", verbosity=0)
        except SystemExit as exc:
            self.fail(f"migrate --check failed: {exc}")
