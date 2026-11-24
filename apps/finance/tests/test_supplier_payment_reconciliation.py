"""AP settlement evidence: approve ≠ settle; ops vs posted AP (1000/400/600)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounting.services import AccountingService, seed_minimal_coa
from apps.billing.models import SupplierInvoiceStatus, SupplierPayment
from apps.core.services import DomainError
from apps.finance.ap_services import (
    POSTED_VOID_BLOCKED,
    WF_SUPPLIER_PAYMENT,
    SupplierInvoiceService,
    authorizable_payable_amount,
    open_payment_authorization_amount,
    payable_balance,
    posted_ap_balance,
)
from apps.parties.models import Party, PartyType
from apps.procurement.models import POLine, PurchaseOrder, POStatus
from apps.workflows.models import ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class SupplierPaymentReconciliationTests(TestCase):
    def setUp(self):
        seed_minimal_coa()
        self.accountant = User.objects.create_user(
            username="recon-acct",
            email="recon-acct@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="recon-mgr",
            email="recon-mgr@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.supplier = Party.objects.create(
            legal_name="Recon Supplier", party_type=PartyType.ORGANIZATION
        )
        self.po = PurchaseOrder.objects.create(
            code="PO-RECON-1", supplier_party=self.supplier, status=POStatus.SENT
        )
        self.line = POLine.objects.create(
            po=self.po,
            description="Goods",
            qty=Decimal("10"),
            unit_price=Decimal("100.00"),
            received_qty=Decimal("10"),
        )

    def _recognized_1000(self):
        inv = SupplierInvoiceService.create_draft(
            supplier_party=self.supplier,
            supplier_invoice_no="RECON-1000",
            lines=[
                {
                    "po_line": self.line,
                    "qty_invoiced": Decimal("10"),
                    "unit_price": Decimal("100.00"),
                }
            ],
            actor=self.accountant,
        )
        matched = SupplierInvoiceService.validate_and_match_or_hold(inv, actor=self.accountant)
        return SupplierInvoiceService.recognize_payable(matched, actor=self.accountant)

    def test_1000_ops_vs_posted_through_400_and_600(self):
        recognized = self._recognized_1000()
        AccountingService.post_to_gl(recognized.journal_entry, actor=self.accountant)
        recognized.journal_entry.refresh_from_db()
        self.assertTrue(recognized.journal_entry.posted)
        self.assertEqual(payable_balance(recognized), Decimal("1000.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("1000.00"))

        req1 = SupplierInvoiceService.request_supplier_payment(
            recognized, amount=Decimal("400.00"), actor=self.accountant
        )
        ApprovalService.decide(req1, approved=True, decided_by=self.manager)
        req1.refresh_from_db()
        self.assertEqual(req1.status, ApprovalStatus.APPROVED)
        self.assertIsNone((req1.payload or {}).get("supplier_payment_id"))
        # Approval alone: ops still 1000; posted still 1000
        self.assertEqual(payable_balance(recognized), Decimal("1000.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("1000.00"))
        self.assertEqual(SupplierPayment.objects.filter(supplier_invoice=recognized).count(), 0)
        self.assertEqual(open_payment_authorization_amount(recognized), Decimal("400.00"))
        self.assertEqual(authorizable_payable_amount(recognized), Decimal("600.00"))

        p1 = SupplierInvoiceService.record_supplier_payment(
            invoice=recognized,
            amount=Decimal("400.00"),
            approval_request=req1,
            reference="BANK-TRX-400",
            paid_at=date(2026, 11, 20),
        )
        self.assertEqual(p1.amount, Decimal("400.00"))
        self.assertEqual(p1.reference, "BANK-TRX-400")
        self.assertEqual(p1.paid_at, date(2026, 11, 20))
        self.assertFalse(p1.journal_entry.posted)
        self.assertEqual(payable_balance(recognized), Decimal("600.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("1000.00"))

        again = SupplierInvoiceService.record_supplier_payment(
            invoice=recognized,
            amount=Decimal("400.00"),
            approval_request=req1,
            reference="BANK-TRX-400-RETRY",
            paid_at=date(2026, 11, 21),
        )
        self.assertEqual(again.pk, p1.pk)
        self.assertEqual(payable_balance(recognized), Decimal("600.00"))
        self.assertEqual(SupplierPayment.objects.filter(supplier_invoice=recognized).count(), 1)

        AccountingService.post_to_gl(p1.journal_entry, actor=self.accountant)
        p1.journal_entry.refresh_from_db()
        self.assertTrue(p1.journal_entry.posted)
        self.assertEqual(payable_balance(recognized), Decimal("600.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("600.00"))

        req2 = SupplierInvoiceService.request_supplier_payment(
            recognized, amount=Decimal("600.00"), actor=self.accountant
        )
        ApprovalService.decide(req2, approved=True, decided_by=self.manager)
        req2.refresh_from_db()
        self.assertEqual(payable_balance(recognized), Decimal("600.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("600.00"))

        p2 = SupplierInvoiceService.record_supplier_payment(
            invoice=recognized,
            amount=Decimal("600.00"),
            approval_request=req2,
            reference="BANK-TRX-600",
            paid_at=date(2026, 11, 22),
        )
        self.assertEqual(payable_balance(recognized), Decimal("0.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("600.00"))
        AccountingService.post_to_gl(p2.journal_entry, actor=self.accountant)
        self.assertEqual(payable_balance(recognized), Decimal("0.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("0.00"))

    def test_mgmt_approve_http_does_not_create_supplier_payment(self):
        recognized = self._recognized_1000()
        AccountingService.post_to_gl(recognized.journal_entry, actor=self.accountant)
        req = SupplierInvoiceService.request_supplier_payment(
            recognized, amount=Decimal("400.00"), actor=self.accountant
        )
        client = Client()
        client.force_login(self.manager)
        resp = client.post(
            reverse("erp:payment_approvals"),
            {"action": "approve_supplier_pay", "approval_id": req.pk},
        )
        self.assertEqual(resp.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.APPROVED)
        self.assertEqual(SupplierPayment.objects.filter(supplier_invoice=recognized).count(), 0)
        self.assertEqual(payable_balance(recognized), Decimal("1000.00"))

    def test_settle_http_creates_evidence_and_drops_ops(self):
        recognized = self._recognized_1000()
        AccountingService.post_to_gl(recognized.journal_entry, actor=self.accountant)
        req = SupplierInvoiceService.request_supplier_payment(
            recognized, amount=Decimal("400.00"), actor=self.accountant
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        client = Client()
        client.force_login(self.accountant)
        resp = client.post(
            reverse("finance:payable_detail", kwargs={"code": recognized.code}),
            {
                "action": "settle_pay",
                "approval_id": req.pk,
                "amount": "400.00",
                "paid_at": "2026-11-20",
                "reference": "SYN-BANK-400",
                "method": "bank",
            },
        )
        self.assertEqual(resp.status_code, 302)
        pay = SupplierPayment.objects.get(supplier_invoice=recognized)
        self.assertEqual(pay.reference, "SYN-BANK-400")
        self.assertEqual(pay.paid_at, date(2026, 11, 20))
        self.assertEqual(payable_balance(recognized), Decimal("600.00"))
        self.assertEqual(posted_ap_balance(recognized), Decimal("1000.00"))

    def test_competing_requests_respect_authorization_reserve(self):
        recognized = self._recognized_1000()
        req1 = SupplierInvoiceService.request_supplier_payment(
            recognized, amount=Decimal("400.00"), actor=self.accountant
        )
        with self.assertRaises(DomainError):
            SupplierInvoiceService.request_supplier_payment(
                recognized, amount=Decimal("600.00"), actor=self.accountant
            )
        ApprovalService.decide(req1, approved=True, decided_by=self.manager)
        # After approve (no settle): remaining authorizable is 600
        self.assertEqual(authorizable_payable_amount(recognized), Decimal("600.00"))
        with self.assertRaises(DomainError):
            SupplierInvoiceService.request_supplier_payment(
                recognized, amount=Decimal("700.00"), actor=self.accountant
            )
        req2 = SupplierInvoiceService.request_supplier_payment(
            recognized, amount=Decimal("600.00"), actor=self.accountant
        )
        self.assertEqual(req2.workflow_code, WF_SUPPLIER_PAYMENT)
        self.assertEqual(payable_balance(recognized), Decimal("1000.00"))
        self.assertEqual(open_payment_authorization_amount(recognized), Decimal("1000.00"))

    def test_settlement_requires_reference_evidence(self):
        recognized = self._recognized_1000()
        req = SupplierInvoiceService.request_supplier_payment(
            recognized, amount=Decimal("400.00"), actor=self.accountant
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        with self.assertRaises(DomainError):
            SupplierInvoiceService.record_supplier_payment(
                invoice=recognized,
                amount=Decimal("400.00"),
                approval_request=req,
                reference="",
            )

    def test_posted_void_still_blocked(self):
        recognized = self._recognized_1000()
        AccountingService.post_to_gl(recognized.journal_entry, actor=self.accountant)
        with self.assertRaises(DomainError) as ctx:
            SupplierInvoiceService.void_supplier_invoice(recognized, actor=self.accountant)
        self.assertEqual(str(ctx.exception), POSTED_VOID_BLOCKED)
        self.assertEqual(recognized.status, SupplierInvoiceStatus.RECOGNIZED)
