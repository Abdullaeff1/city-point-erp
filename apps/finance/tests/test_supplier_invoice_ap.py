from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounting.models import JournalEntry
from apps.accounting.services import seed_minimal_coa
from apps.billing.models import SupplierInvoiceStatus
from apps.core.services import DomainError
from apps.finance.ap_services import SupplierInvoiceService, available_qty_for_po_line
from apps.parties.models import Party, PartyType
from apps.procurement.models import POLine, PurchaseOrder, POStatus

User = get_user_model()


class SupplierInvoiceApTests(TestCase):
    def setUp(self):
        seed_minimal_coa()
        self.accountant = User.objects.create_user(
            username="ap-acct",
            email="ap-acct@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.supplier = Party.objects.create(
            legal_name="AP Supplier", party_type=PartyType.ORGANIZATION
        )
        self.po = PurchaseOrder.objects.create(
            code="PO-AP-1", supplier_party=self.supplier, status=POStatus.SENT
        )
        self.line = POLine.objects.create(
            po=self.po,
            description="Widget",
            qty=Decimal("10"),
            unit_price=Decimal("5.00"),
            received_qty=Decimal("6"),
        )
        self.client = Client()

    def test_10_6_10_hold_keeps_qty_no_journal(self):
        inv = SupplierInvoiceService.create_draft(
            supplier_party=self.supplier,
            supplier_invoice_no="SUP-10",
            lines=[
                {
                    "po_line": self.line,
                    "qty_invoiced": Decimal("10"),
                    "unit_price": Decimal("5.00"),
                }
            ],
            actor=self.accountant,
        )
        out = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        self.assertEqual(out.status, SupplierInvoiceStatus.HOLD)
        line = out.lines.get()
        self.assertEqual(line.qty_invoiced, Decimal("10"))
        self.assertEqual(line.variance_qty, Decimal("4"))
        self.assertIsNone(out.journal_entry_id)
        self.assertEqual(
            JournalEntry.objects.filter(source_ref=f"supplier_invoice:{out.pk}").count(),
            0,
        )
        # HOLD does not reserve
        self.assertEqual(available_qty_for_po_line(self.line), Decimal("6"))

    def test_invoice_for_six_matched_and_recognized(self):
        inv = SupplierInvoiceService.create_draft(
            supplier_party=self.supplier,
            supplier_invoice_no="SUP-6",
            lines=[
                {
                    "po_line": self.line,
                    "qty_invoiced": Decimal("6"),
                    "unit_price": Decimal("5.00"),
                }
            ],
            actor=self.accountant,
        )
        matched = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        self.assertEqual(matched.status, SupplierInvoiceStatus.MATCHED)
        self.assertEqual(available_qty_for_po_line(self.line), Decimal("0"))
        recognized = SupplierInvoiceService.recognize_payable(
            matched, actor=self.accountant
        )
        self.assertEqual(recognized.status, SupplierInvoiceStatus.RECOGNIZED)
        self.assertIsNotNone(recognized.journal_entry_id)
        je = recognized.journal_entry
        self.assertFalse(je.posted)
        self.assertEqual(je.source, "billing.supplier_invoice")

    def test_void_releases_reservation(self):
        inv = SupplierInvoiceService.create_draft(
            supplier_party=self.supplier,
            supplier_invoice_no="SUP-V",
            lines=[{"po_line": self.line, "qty_invoiced": Decimal("6"), "unit_price": 5}],
            actor=self.accountant,
        )
        SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        self.assertEqual(available_qty_for_po_line(self.line), Decimal("0"))
        SupplierInvoiceService.void_supplier_invoice(inv, actor=self.accountant)
        self.line.refresh_from_db()
        self.assertEqual(available_qty_for_po_line(self.line), Decimal("6"))

    def test_revalidate_after_further_receipt(self):
        inv = SupplierInvoiceService.create_draft(
            supplier_party=self.supplier,
            supplier_invoice_no="SUP-RV",
            lines=[{"po_line": self.line, "qty_invoiced": Decimal("10"), "unit_price": 5}],
            actor=self.accountant,
        )
        held = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        self.assertEqual(held.status, SupplierInvoiceStatus.HOLD)
        self.line.received_qty = Decimal("10")
        self.line.save(update_fields=["received_qty"])
        out = SupplierInvoiceService.revalidate_hold(held, actor=self.accountant)
        self.assertEqual(out.status, SupplierInvoiceStatus.MATCHED)

    def test_duplicate_supplier_invoice_no(self):
        kwargs = dict(
            supplier_party=self.supplier,
            supplier_invoice_no="DUP-1",
            lines=[{"po_line": self.line, "qty_invoiced": Decimal("1"), "unit_price": 5}],
            actor=self.accountant,
        )
        SupplierInvoiceService.create_draft(**kwargs)
        with self.assertRaises(DomainError):
            SupplierInvoiceService.create_draft(**kwargs)

    def test_payables_http_pages(self):
        self.client.force_login(self.accountant)
        for name in ("finance:payables", "finance:payable_create", "finance:home"):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)


class SupplierInvoiceConcurrencyTests(TransactionTestCase):
    def setUp(self):
        seed_minimal_coa()
        self.accountant = User.objects.create_user(
            username="ap-conc",
            email="ap-conc@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.supplier = Party.objects.create(
            legal_name="Conc Supplier", party_type=PartyType.ORGANIZATION
        )
        self.po = PurchaseOrder.objects.create(
            code="PO-CONC-1", supplier_party=self.supplier, status=POStatus.SENT
        )
        self.line = POLine.objects.create(
            po=self.po,
            description="Widget",
            qty=Decimal("10"),
            unit_price=Decimal("5.00"),
            received_qty=Decimal("6"),
        )

    def test_two_invoices_compete_for_six_received(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-level locks")
        a = SupplierInvoiceService.create_draft(
            supplier_party=self.supplier,
            supplier_invoice_no="CONC-A",
            lines=[{"po_line": self.line, "qty_invoiced": Decimal("6"), "unit_price": 5}],
            actor=self.accountant,
        )
        b = SupplierInvoiceService.create_draft(
            supplier_party=self.supplier,
            supplier_invoice_no="CONC-B",
            lines=[{"po_line": self.line, "qty_invoiced": Decimal("6"), "unit_price": 5}],
            actor=self.accountant,
        )
        matched_a = SupplierInvoiceService.validate_and_match_or_hold(a, actor=self.accountant)
        self.assertEqual(matched_a.status, SupplierInvoiceStatus.MATCHED)
        out_b = SupplierInvoiceService.validate_and_match_or_hold(b, actor=self.accountant)
        self.assertEqual(out_b.status, SupplierInvoiceStatus.HOLD)
        self.assertEqual(available_qty_for_po_line(self.line), Decimal("0"))
