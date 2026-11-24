"""Supplier invoice lifecycle, void protection, and AP settlement (1000/400/600)."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.accounting.services import AccountingService, seed_minimal_coa
from apps.billing.models import SupplierInvoiceStatus
from apps.core.services import DomainError
from apps.finance.ap_services import (
    POSTED_VOID_BLOCKED,
    WF_SUPPLIER_PAYMENT,
    SupplierInvoiceService,
    available_qty_for_po_line,
    payable_balance,
    posted_ap_balance,
    supplier_invoice_gross,
)
from apps.parties.models import Party, PartyType
from apps.procurement.models import POLine, PurchaseOrder, POStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class SupplierInvoiceLifecycleTests(TestCase):
    def setUp(self):
        seed_minimal_coa()
        self.accountant = User.objects.create_user(
            username="life-acct",
            email="life-acct@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="life-mgr",
            email="life-mgr@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.supplier = Party.objects.create(
            legal_name="Life Supplier", party_type=PartyType.ORGANIZATION
        )
        self.po = PurchaseOrder.objects.create(
            code="PO-LIFE-1", supplier_party=self.supplier, status=POStatus.SENT
        )
        self.line = POLine.objects.create(
            po=self.po,
            description="Goods",
            qty=Decimal("10"),
            unit_price=Decimal("100.00"),
            received_qty=Decimal("6"),
        )

    def _draft(self, *, no, qty, price=None):
        return SupplierInvoiceService.create_draft(
            supplier_party=self.supplier,
            supplier_invoice_no=no,
            lines=[
                {
                    "po_line": self.line,
                    "qty_invoiced": Decimal(str(qty)),
                    "unit_price": Decimal(str(price if price is not None else self.line.unit_price)),
                }
            ],
            actor=self.accountant,
        )

    def test_10_6_10_hold_then_revalidate_after_remaining_four(self):
        inv = self._draft(no="L-10", qty=10)
        held = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        self.assertEqual(held.status, SupplierInvoiceStatus.HOLD)
        self.assertEqual(held.lines.get().qty_invoiced, Decimal("10"))
        self.assertEqual(held.lines.get().variance_qty, Decimal("4"))
        self.assertEqual(available_qty_for_po_line(self.line), Decimal("6"))

        self.line.received_qty = Decimal("10")
        self.line.save(update_fields=["received_qty"])
        matched = SupplierInvoiceService.revalidate_hold(held, actor=self.accountant)
        self.assertEqual(matched.status, SupplierInvoiceStatus.MATCHED)
        self.assertEqual(available_qty_for_po_line(self.line), Decimal("0"))
        recognized = SupplierInvoiceService.recognize_payable(matched, actor=self.accountant)
        self.assertEqual(recognized.status, SupplierInvoiceStatus.RECOGNIZED)
        self.assertFalse(recognized.journal_entry.posted)

    def test_void_before_recognition_releases_qty(self):
        inv = self._draft(no="L-V1", qty=6)
        matched = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        self.assertEqual(matched.status, SupplierInvoiceStatus.MATCHED)
        SupplierInvoiceService.void_supplier_invoice(matched, actor=self.accountant)
        self.assertEqual(available_qty_for_po_line(self.line), Decimal("6"))

    def test_void_after_unposted_recognition_reverses_and_releases(self):
        inv = self._draft(no="L-V2", qty=6)
        matched = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        recognized = SupplierInvoiceService.recognize_payable(matched, actor=self.accountant)
        je = recognized.journal_entry
        self.assertFalse(je.posted)
        voided = SupplierInvoiceService.void_supplier_invoice(recognized, actor=self.accountant)
        self.assertEqual(voided.status, SupplierInvoiceStatus.VOID)
        self.assertEqual(available_qty_for_po_line(self.line), Decimal("6"))
        je.refresh_from_db()
        self.assertIsNotNone(je.reversed_entry_id)

    def test_posted_recognition_blocks_void_and_keeps_reservation(self):
        inv = self._draft(no="L-V3", qty=6)
        matched = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        recognized = SupplierInvoiceService.recognize_payable(matched, actor=self.accountant)
        AccountingService.post_to_gl(recognized.journal_entry, actor=self.accountant)
        recognized.journal_entry.refresh_from_db()
        self.assertTrue(recognized.journal_entry.posted)
        with self.assertRaises(DomainError) as ctx:
            SupplierInvoiceService.void_supplier_invoice(recognized, actor=self.accountant)
        self.assertEqual(str(ctx.exception), POSTED_VOID_BLOCKED)
        # Qty still reserved — second invoice cannot take the six units while payable stands
        self.assertEqual(available_qty_for_po_line(self.line), Decimal("0"))
        other = self._draft(no="L-V3B", qty=6)
        held = SupplierInvoiceService.validate_and_match_or_hold(other, actor=self.accountant)
        self.assertEqual(held.status, SupplierInvoiceStatus.HOLD)
        recognized.refresh_from_db()
        self.assertEqual(recognized.status, SupplierInvoiceStatus.RECOGNIZED)

    def test_settlement_1000_with_400_and_600(self):
        self.line.unit_price = Decimal("100.00")
        self.line.received_qty = Decimal("10")
        self.line.save(update_fields=["unit_price", "received_qty"])
        inv = self._draft(no="L-1000", qty=10, price="100.00")
        matched = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        recognized = SupplierInvoiceService.recognize_payable(matched, actor=self.accountant)
        AccountingService.post_to_gl(recognized.journal_entry, actor=self.accountant)
        self.assertEqual(supplier_invoice_gross(recognized), Decimal("1000.00"))
        self.assertEqual(payable_balance(recognized), Decimal("1000.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("1000.00"))

        req1 = SupplierInvoiceService.request_supplier_payment(
            recognized, amount=Decimal("400.00"), actor=self.accountant
        )
        self.assertEqual(req1.workflow_code, WF_SUPPLIER_PAYMENT)
        ApprovalService.decide(req1, approved=True, decided_by=self.manager)
        req1.refresh_from_db()
        self.assertEqual(payable_balance(recognized), Decimal("1000.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("1000.00"))
        p1 = SupplierInvoiceService.record_supplier_payment(
            invoice=recognized,
            amount=Decimal("400.00"),
            approval_request=req1,
            reference="LIFE-400",
        )
        self.assertEqual(p1.amount, Decimal("400.00"))
        self.assertEqual(payable_balance(recognized), Decimal("600.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("1000.00"))
        again = SupplierInvoiceService.record_supplier_payment(
            invoice=recognized,
            amount=Decimal("400.00"),
            approval_request=req1,
            reference="LIFE-400",
        )
        self.assertEqual(again.pk, p1.pk)
        self.assertEqual(payable_balance(recognized), Decimal("600.00"))
        AccountingService.post_to_gl(p1.journal_entry, actor=self.accountant)
        self.assertEqual(posted_ap_balance(recognized), Decimal("600.00"))

        req2 = SupplierInvoiceService.request_supplier_payment(
            recognized, amount=Decimal("600.00"), actor=self.accountant
        )
        ApprovalService.decide(req2, approved=True, decided_by=self.manager)
        req2.refresh_from_db()
        self.assertEqual(payable_balance(recognized), Decimal("600.00"))
        p2 = SupplierInvoiceService.record_supplier_payment(
            invoice=recognized,
            amount=Decimal("600.00"),
            approval_request=req2,
            reference="LIFE-600",
        )
        self.assertEqual(p2.amount, Decimal("600.00"))
        self.assertEqual(payable_balance(recognized), Decimal("0.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("600.00"))
        AccountingService.post_to_gl(p2.journal_entry, actor=self.accountant)
        self.assertEqual(payable_balance(recognized), Decimal("0.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("0.00"))
        self.assertEqual(recognized.payments.count(), 2)
        self.assertEqual(p1.journal_entry.source, "billing.supplier_payment")

        with self.assertRaises(DomainError):
            SupplierInvoiceService.request_supplier_payment(
                recognized, amount=Decimal("0.01"), actor=self.accountant
            )

    def test_reject_allocation_exceeding_outstanding_on_record(self):
        self.line.received_qty = Decimal("10")
        self.line.unit_price = Decimal("100")
        self.line.save(update_fields=["received_qty", "unit_price"])
        inv = self._draft(no="L-OVER", qty=10, price=100)
        matched = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        recognized = SupplierInvoiceService.recognize_payable(matched, actor=self.accountant)
        req = SupplierInvoiceService.request_supplier_payment(
            recognized, amount=Decimal("1000.00"), actor=self.accountant
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        req.refresh_from_db()
        with self.assertRaises(DomainError):
            SupplierInvoiceService.record_supplier_payment(
                invoice=recognized,
                amount=Decimal("1000.01"),
                approval_request=req,
                reference="OVER-REF",
            )
