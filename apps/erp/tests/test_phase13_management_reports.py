"""Phase 13 — management dashboard, as-of metrics, drill-down, exports."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import Role
from apps.accounting.coa import code_for
from apps.accounting.models import JournalEntry
from apps.accounting.services import AccountingService, seed_minimal_coa
from apps.billing.models import Charge, ChargeSource, InvoiceStatus
from apps.billing.services import (
    confirm_invoice,
    generate_invoice_from_charges,
    invoice_balance,
    invoice_balance_as_of,
    record_payment,
)
from apps.erp.exec_reports import (
    build_exec_bundle,
    build_finance_report,
    build_fm_report,
    build_property_report,
    build_warehouse_report,
    exec_report_xlsx_response,
    parse_report_params,
)
from apps.leases.models import Lease, LeaseStatus
from apps.maintenance.models import WorkOrder, WorkOrderStatus
from apps.parties.models import Party, PartyType
from apps.parties.resolvers import party_for_company
from apps.property.models import Building, CommercialStatus, Floor, Occupancy, Space
from apps.residents.models import ResidentCompany
from apps.warehouse.models import SKU, Stock, Warehouse
from apps.workflows.services import ApprovalService

User = get_user_model()


def _approved_pay(invoice, amount, *, accountant, manager, reference=""):
    req = ApprovalService.request(
        workflow_code="finance.payment",
        requested_by=accountant,
        entity=invoice,
        payload={
            "invoice_id": invoice.pk,
            "invoice_code": invoice.code,
            "amount": str(amount),
            "method": "bank",
            "reference": reference,
        },
    )
    ApprovalService.decide(req, approved=True, decided_by=manager)
    req.refresh_from_db()
    return req


class Phase13ManagementReportsTests(TestCase):
    def setUp(self):
        seed_minimal_coa()
        self.manager = User.objects.create_user(
            username="p13-mgr",
            email="p13-mgr@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.accountant = User.objects.create_user(
            username="p13-acc",
            email="p13-acc@test.az",
            password="Pass12345!",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.reception = User.objects.create_user(
            username="p13-rec",
            email="p13-rec@test.az",
            password="Pass12345!",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.co_a = ResidentCompany.objects.create(
            name="P13 Co A", slug="p13-a", portal_active=True
        )
        self.co_b = ResidentCompany.objects.create(
            name="P13 Co B", slug="p13-b", portal_active=True
        )
        self.party_a = party_for_company(self.co_a, ensure=True)
        self.party_b = party_for_company(self.co_b, ensure=True)
        building = Building.objects.create(code="P13B", name="P13B")
        floor = Floor.objects.create(building=building, code="P13F", name="1")
        self.space = Space.objects.create(
            code="P13-100",
            name="Office 100",
            floor=floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            commercial_status=CommercialStatus.CONTRACTED,
            occupancy=Occupancy.VACANT,
        )
        self.lease = Lease.objects.create(
            code="LS-P13-FUT",
            party=self.party_a,
            space=self.space,
            status=LeaseStatus.SIGNED,
            start_date=date(2026, 12, 1),
            rent=Decimal("1000"),
            currency="AZN",
        )
        self.wh1 = Warehouse.objects.create(code="P13-W1", name="W1")
        self.wh2 = Warehouse.objects.create(code="P13-W2", name="W2")
        self.sku_pcs = SKU.objects.create(
            code="P13-PCS", name="Bolt", unit="ədəd", reorder_level=Decimal("10")
        )
        self.sku_l = SKU.objects.create(
            code="P13-L", name="Oil", unit="litr", reorder_level=Decimal("5")
        )
        Stock.objects.create(
            sku=self.sku_pcs, warehouse=self.wh1, quantity=Decimal("3"), reserved_quantity=Decimal("1")
        )
        Stock.objects.create(
            sku=self.sku_l, warehouse=self.wh2, quantity=Decimal("20"), reserved_quantity=Decimal("0")
        )
        self.client = Client()
        self.client.force_login(self.manager)

    def test_future_start_lease_nov_vs_dec(self):
        nov = build_property_report(
            {"date_from": date(2026, 11, 1), "date_to": date(2026, 11, 30), "company_id": None}
        )
        self.assertEqual(nov["reserved_m2"], 100.0)
        self.assertEqual(nov["occupied_m2"], 0.0)
        self.assertEqual(nov["available_m2"], 0.0)
        self.assertEqual(nov["occupancy_pct"], 0.0)
        self.assertEqual(len(nov["reserved_rows"]), 1)
        self.assertEqual(nov["reserved_rows"][0]["lease_code"], "LS-P13-FUT")

        dec = build_property_report(
            {"date_from": date(2026, 12, 1), "date_to": date(2026, 12, 1), "company_id": None}
        )
        self.assertEqual(dec["occupied_m2"], 100.0)
        self.assertEqual(dec["reserved_m2"], 0.0)
        self.assertEqual(dec["occupancy_pct"], 100.0)
        self.assertIn("start/end", nov["rule"].lower() or nov["rule"])

    def test_ar_operational_vs_posted_payment_reconciling(self):
        charge = Charge.objects.create(
            party=self.party_a,
            source=ChargeSource.RENT,
            description="P13 1000",
            amount=Decimal("1000.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party_a, [charge.pk], apply_vat=False)
        # Force issue date 28 Nov
        inv.issue_date = date(2026, 11, 28)
        inv.due_date = date(2026, 12, 28)
        inv.save(update_fields=["issue_date", "due_date"])
        confirm_invoice(inv)
        inv.refresh_from_db()
        inv.issue_date = date(2026, 11, 28)
        inv.save(update_fields=["issue_date"])
        je_inv = JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv.pk}")
        je_inv.entry_date = date(2026, 11, 28)
        je_inv.save(update_fields=["entry_date"])
        AccountingService.post_to_gl(je_inv, actor=self.accountant)

        nov30 = build_finance_report(
            {"date_from": date(2026, 11, 1), "date_to": date(2026, 11, 30), "company_id": None}
        )
        self.assertEqual(nov30["operational_ar"], Decimal("1000.00"))
        self.assertEqual(nov30["posted_ar"], Decimal("1000.00"))

        req = _approved_pay(
            inv, Decimal("400.00"), accountant=self.accountant, manager=self.manager, reference="P13-400"
        )
        pay = record_payment(
            invoice=inv, amount=Decimal("400.00"), approval_request=req, method="bank", reference="P13-400"
        )
        pay.paid_at = date(2026, 12, 3)
        pay.save(update_fields=["paid_at"])
        je_pay = JournalEntry.objects.get(source="billing.payment", source_ref=f"payment:{pay.pk}")
        je_pay.entry_date = date(2026, 12, 3)
        je_pay.save(update_fields=["entry_date"])
        self.assertFalse(je_pay.posted)

        self.assertEqual(invoice_balance(inv), Decimal("600.00"))
        self.assertEqual(invoice_balance_as_of(inv, date(2026, 12, 3)), Decimal("600.00"))

        dec3 = build_finance_report(
            {"date_from": date(2026, 12, 1), "date_to": date(2026, 12, 3), "company_id": None}
        )
        self.assertEqual(dec3["operational_ar"], Decimal("600.00"))
        self.assertEqual(dec3["posted_ar"], Decimal("1000.00"))
        self.assertEqual(dec3["reconciling_unposted_total"], Decimal("400.00"))

        AccountingService.post_to_gl(je_pay, actor=self.accountant)
        dec4 = build_finance_report(
            {"date_from": date(2026, 12, 1), "date_to": date(2026, 12, 4), "company_id": None}
        )
        self.assertEqual(dec4["operational_ar"], Decimal("600.00"))
        self.assertEqual(dec4["posted_ar"], Decimal("600.00"))
        self.assertEqual(dec4["reconciling_unposted_total"], Decimal("0"))

    def test_wo_open_as_of_after_later_close(self):
        wo = WorkOrder.objects.create(
            code="WO-P13-1",
            title="Leak",
            status=WorkOrderStatus.IN_PROGRESS,
            party=self.party_a,
        )
        # Backdate create to October
        WorkOrder.objects.filter(pk=wo.pk).update(
            created_at=timezone.make_aware(datetime(2026, 10, 1, 10, 0, 0))
        )
        wo.refresh_from_db()
        # Close "today" relative to Dec 10
        closed_at = timezone.make_aware(datetime(2026, 12, 10, 12, 0, 0))
        WorkOrder.objects.filter(pk=wo.pk).update(
            status=WorkOrderStatus.COMPLETED, completed_at=closed_at
        )

        oct_end = build_fm_report(
            {"date_from": date(2026, 10, 1), "date_to": date(2026, 10, 31), "company_id": None}
        )
        self.assertGreaterEqual(oct_end["open_wo"], 1)
        codes = [r["code"] for rows in oct_end["aging_rows"].values() for r in rows]
        self.assertIn("WO-P13-1", codes)

        after = build_fm_report(
            {"date_from": date(2026, 12, 1), "date_to": date(2026, 12, 10), "company_id": None}
        )
        codes_after = [r["code"] for rows in after["aging_rows"].values() for r in rows]
        self.assertNotIn("WO-P13-1", codes_after)

    def test_warehouse_units_not_mixed_and_low_stock(self):
        wh = build_warehouse_report(
            {"date_from": date(2026, 11, 1), "date_to": date(2026, 11, 30), "company_id": None}
        )
        self.assertEqual(wh["low_stock_count"], 1)  # pcs 3 <= 10
        self.assertTrue(wh["issued_qty"] == Decimal("0") or wh["issued_qty"] is not None)
        units = {b["unit"] for b in wh["by_unit"]}
        self.assertIn("ədəd", units)
        self.assertIn("litr", units)
        self.assertFalse(wh["historical_stock"])

    def test_dashboard_drill_export_same_filters_and_acl(self):
        params_q = "date_from=2026-11-01&date_to=2026-11-30"
        home = self.client.get(reverse("erp:reports") + f"?{params_q}&tab=overview")
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, "Doluluq")
        self.assertContains(home, "Əməliyyat AR")
        self.assertContains(home, "Posted AR")

        drill = self.client.get(
            reverse("erp:reports_drill", kwargs={"section": "property"}) + f"?{params_q}"
        )
        self.assertEqual(drill.status_code, 200)
        self.assertContains(drill, "LS-P13-FUT")
        self.assertContains(drill, "Rezerv")

        export = self.client.get(reverse("erp:reports_export") + f"?{params_q}")
        self.assertEqual(export.status_code, 200)
        wb = load_workbook(BytesIO(export.content))
        self.assertIn("Meta", wb.sheetnames)
        self.assertIn("Occupancy", wb.sheetnames)
        self.assertIn("AR", wb.sheetnames)
        meta = wb["Meta"]
        meta_vals = {meta.cell(r, 1).value: meta.cell(r, 2).value for r in range(1, 10)}
        self.assertEqual(str(meta_vals.get("date_to / as_of")), "2026-11-30")
        occ = wb["Occupancy"]
        buckets = [occ.cell(r, 1).value for r in range(2, occ.max_row + 1)]
        self.assertIn("reserved", buckets)

        # Bundle totals match drill
        params = parse_report_params({"date_from": "2026-11-01", "date_to": "2026-11-30"})
        bundle = build_exec_bundle(params, user=self.manager)
        self.assertEqual(bundle["property"]["reserved_m2"], 100.0)
        self.assertEqual(home.context["prop"]["reserved_m2"], 100.0)
        self.assertEqual(drill.context["data"]["reserved_m2"], 100.0)

        # Reception denied
        rec = Client()
        rec.force_login(self.reception)
        self.assertEqual(rec.get(reverse("erp:reports")).status_code, 302)
        self.assertEqual(rec.get(reverse("erp:reports_export")).status_code, 302)
        self.assertEqual(
            rec.get(reverse("erp:reports_drill", kwargs={"section": "finance"})).status_code,
            302,
        )

        # Accountant cannot open management reports (finance portal only)
        acc = Client()
        acc.force_login(self.accountant)
        self.assertEqual(acc.get(reverse("erp:reports")).status_code, 302)

    def test_empty_vs_zero_denominator(self):
        Space.objects.all().delete()
        Lease.objects.all().delete()
        empty = build_property_report(
            {"date_from": date(2026, 11, 1), "date_to": date(2026, 11, 30), "company_id": None}
        )
        self.assertTrue(empty["occupancy_unavailable"])
        self.assertEqual(empty["occupancy_display"], "—")

    def test_company_scope_does_not_leak(self):
        charge_b = Charge.objects.create(
            party=self.party_b,
            source=ChargeSource.RENT,
            description="SECRET-B",
            amount=Decimal("777.00"),
            currency="AZN",
        )
        inv_b = generate_invoice_from_charges(self.party_b, [charge_b.pk], apply_vat=False)
        confirm_invoice(inv_b)
        params = {
            "date_from": timezone.localdate() - timedelta(days=5),
            "date_to": timezone.localdate(),
            "company_id": self.co_a.pk,
        }
        fin = build_finance_report(params)
        codes = [r["code"] for r in fin["open_rows"]]
        self.assertNotIn(inv_b.code, codes)
