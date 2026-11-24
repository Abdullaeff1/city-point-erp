"""AP payment queue, cancel unused auth, unique bank ref, ops vs posted explain."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounting.services import AccountingService, seed_minimal_coa
from apps.billing.models import SupplierPayment
from apps.core.services import DomainError
from apps.finance.ap_services import (
    SupplierInvoiceService,
    authorizable_payable_amount,
    open_payment_authorization_amount,
    payable_balance,
    payable_recon_snapshot,
    posted_ap_balance,
)
from apps.parties.models import Party, PartyType
from apps.procurement.models import POLine, PurchaseOrder, POStatus
from apps.workflows.models import ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class SupplierPaymentQueueTests(TestCase):
    def setUp(self):
        seed_minimal_coa()
        self.accountant = User.objects.create_user(
            username="queue-acct",
            email="queue-acct@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="queue-mgr",
            email="queue-mgr@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.supplier = Party.objects.create(
            legal_name="Queue Supplier", party_type=PartyType.ORGANIZATION
        )
        self.po = PurchaseOrder.objects.create(
            code="PO-QUEUE-1", supplier_party=self.supplier, status=POStatus.SENT
        )
        self.line = POLine.objects.create(
            po=self.po,
            description="Goods",
            qty=Decimal("10"),
            unit_price=Decimal("100.00"),
            received_qty=Decimal("10"),
        )
        self.client = Client()
        self.client.force_login(self.accountant)

    def _recognized(self, no="Q-1000"):
        inv = SupplierInvoiceService.create_draft(
            supplier_party=self.supplier,
            supplier_invoice_no=no,
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
        recognized = SupplierInvoiceService.recognize_payable(matched, actor=self.accountant)
        AccountingService.post_to_gl(recognized.journal_entry, actor=self.accountant)
        return recognized

    def test_payables_queue_filters_find_each_stage(self):
        inv = self._recognized()
        req = SupplierInvoiceService.request_supplier_payment(
            inv, amount=Decimal("400.00"), actor=self.accountant
        )
        r = self.client.get(reverse("finance:payables") + "?queue=pending_approval")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, inv.code)

        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        r = self.client.get(reverse("finance:payables") + "?queue=awaiting_settle")
        self.assertContains(r, inv.code)
        self.assertNotContains(
            self.client.get(reverse("finance:payables") + "?queue=pending_approval"),
            inv.code,
        )

        pay = SupplierInvoiceService.record_supplier_payment(
            invoice=inv,
            amount=Decimal("400.00"),
            approval_request=req,
            reference="QUEUE-REF-400",
            paid_at=date(2026, 11, 21),
        )
        r = self.client.get(reverse("finance:payables") + "?queue=unposted_settle")
        self.assertContains(r, "QUEUE-REF-400")
        self.assertContains(r, inv.code)

        AccountingService.post_to_gl(pay.journal_entry, actor=self.accountant)
        r = self.client.get(reverse("finance:payables") + "?queue=posted_settle")
        self.assertContains(r, "QUEUE-REF-400")
        unposted = self.client.get(reverse("finance:payables") + "?queue=unposted_settle")
        self.assertNotContains(unposted, "QUEUE-REF-400")

    def test_cancel_approved_unused_releases_reserve(self):
        inv = self._recognized("Q-CANCEL")
        req = SupplierInvoiceService.request_supplier_payment(
            inv, amount=Decimal("400.00"), actor=self.accountant
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        self.assertEqual(open_payment_authorization_amount(inv), Decimal("400.00"))
        self.assertEqual(authorizable_payable_amount(inv), Decimal("600.00"))

        cancelled = SupplierInvoiceService.cancel_payment_authorization(
            req, actor=self.accountant, reason="Bank transfer failed / abandoned"
        )
        self.assertEqual(cancelled.status, ApprovalStatus.CANCELLED)
        self.assertIn("failed", cancelled.comment.lower())
        self.assertEqual(open_payment_authorization_amount(inv), Decimal("0.00"))
        self.assertEqual(authorizable_payable_amount(inv), Decimal("1000.00"))
        self.assertEqual(payable_balance(inv), Decimal("1000.00"))
        self.assertEqual(SupplierPayment.objects.filter(supplier_invoice=inv).count(), 0)

        # Reason required
        req2 = SupplierInvoiceService.request_supplier_payment(
            inv, amount=Decimal("100.00"), actor=self.accountant
        )
        with self.assertRaises(DomainError):
            SupplierInvoiceService.cancel_payment_authorization(req2, actor=self.accountant, reason="")

    def test_cancel_http_on_payable_detail(self):
        inv = self._recognized("Q-HTTP")
        req = SupplierInvoiceService.request_supplier_payment(
            inv, amount=Decimal("250.00"), actor=self.accountant
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        resp = self.client.post(
            reverse("finance:payable_detail", kwargs={"code": inv.code}),
            {
                "action": "cancel_pay_auth",
                "approval_id": req.pk,
                "reason": "Transfer baş tutmadı",
            },
        )
        self.assertEqual(resp.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.CANCELLED)
        self.assertEqual(authorizable_payable_amount(inv), Decimal("1000.00"))

    def test_duplicate_bank_reference_rejected_across_approvals(self):
        inv = self._recognized("Q-REF1")
        # Use remaining qty capacity: first payment 400, need second invoice for second settle
        # Same invoice two payments with same ref should also fail.
        req1 = SupplierInvoiceService.request_supplier_payment(
            inv, amount=Decimal("400.00"), actor=self.accountant
        )
        ApprovalService.decide(req1, approved=True, decided_by=self.manager)
        SupplierInvoiceService.record_supplier_payment(
            invoice=inv,
            amount=Decimal("400.00"),
            approval_request=req1,
            reference="SAME-BANK-TRX",
        )
        req2 = SupplierInvoiceService.request_supplier_payment(
            inv, amount=Decimal("600.00"), actor=self.accountant
        )
        ApprovalService.decide(req2, approved=True, decided_by=self.manager)
        with self.assertRaises(DomainError) as ctx:
            SupplierInvoiceService.record_supplier_payment(
                invoice=inv,
                amount=Decimal("600.00"),
                approval_request=req2,
                reference="same-bank-trx",  # case-insensitive duplicate
            )
        self.assertIn("reference", str(ctx.exception).lower())

    def test_recon_explains_ops_vs_posted_and_post_keeps_ops(self):
        inv = self._recognized("Q-RECON")
        self.assertEqual(payable_balance(inv), Decimal("1000.00"))
        self.assertEqual(posted_ap_balance(inv), Decimal("1000.00"))
        snap0 = payable_recon_snapshot(inv)
        self.assertEqual(snap0["diff"], Decimal("0.00"))

        req = SupplierInvoiceService.request_supplier_payment(
            inv, amount=Decimal("400.00"), actor=self.accountant
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        pay = SupplierInvoiceService.record_supplier_payment(
            invoice=inv,
            amount=Decimal("400.00"),
            approval_request=req,
            reference="RECON-400",
        )
        ops_before_post = payable_balance(inv)
        self.assertEqual(ops_before_post, Decimal("600.00"))
        self.assertEqual(posted_ap_balance(inv), Decimal("1000.00"))
        snap = payable_recon_snapshot(inv)
        self.assertEqual(snap["diff"], Decimal("-400.00"))
        self.assertEqual(snap["unposted_settlement_amount"], Decimal("400.00"))
        self.assertTrue(snap["explanations"])

        AccountingService.post_to_gl(pay.journal_entry, actor=self.accountant)
        self.assertEqual(payable_balance(inv), ops_before_post)  # ops unchanged by JE post
        self.assertEqual(posted_ap_balance(inv), Decimal("600.00"))
        snap2 = payable_recon_snapshot(inv)
        self.assertEqual(snap2["diff"], Decimal("0.00"))
        self.assertEqual(snap2["unposted_settlement_amount"], Decimal("0.00"))

        detail = self.client.get(reverse("finance:payable_detail", kwargs={"code": inv.code}))
        self.assertContains(detail, "Kreditor uzlaşma")
        self.assertEqual(detail.context["recon"]["ops"], Decimal("600.00"))
        self.assertEqual(detail.context["recon"]["posted"], Decimal("600.00"))
