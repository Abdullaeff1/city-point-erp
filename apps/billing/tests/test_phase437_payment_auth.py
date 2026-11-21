"""Phase 4.3.7 — record_payment requires APPROVED finance.payment ApprovalRequest."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.billing.models import Charge, ChargeSource, InvoiceStatus, Payment
from apps.billing.services import generate_invoice_from_charges, confirm_invoice, record_payment
from apps.core.services import DomainError
from apps.parties.models import Party, PartyType
from apps.workflows.models import ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


def _approved_pay_req(invoice, amount, *, requested_by, decided_by, method="bank", reference=""):
    req = ApprovalService.request(
        workflow_code="finance.payment",
        requested_by=requested_by,
        entity=invoice,
        payload={
            "invoice_id": invoice.pk,
            "invoice_code": invoice.code,
            "amount": str(amount),
            "method": method,
            "reference": reference,
        },
    )
    ApprovalService.decide(req, approved=True, decided_by=decided_by)
    req.refresh_from_db()
    return req


class Phase437PaymentAuthTests(TestCase):
    def setUp(self):
        self.accountant = User.objects.create_user(
            username="p437-acc", email="p437a@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.manager = User.objects.create_user(
            username="p437-mgmt", email="p437m@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.party = Party.objects.create(legal_name="PayAuth Co", party_type=PartyType.ORGANIZATION)
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="Auth rent",
            amount=Decimal("100.00"),
            currency="AZN",
        )
        self.inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(self.inv)

    def test_approved_payment_succeeds_and_consumes(self):
        req = _approved_pay_req(
            self.inv, self.inv.total, requested_by=self.accountant, decided_by=self.manager, reference="A1"
        )
        pay = record_payment(
            invoice=self.inv,
            amount=self.inv.total,
            method="bank",
            reference="A1",
            approval_request=req,
        )
        self.assertEqual(pay.amount, Decimal("100.00"))
        req.refresh_from_db()
        self.assertEqual(req.payload.get("payment_id"), pay.pk)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, InvoiceStatus.PAID)

    def test_replay_same_approval_idempotent(self):
        req = _approved_pay_req(
            self.inv, self.inv.total, requested_by=self.accountant, decided_by=self.manager
        )
        p1 = record_payment(
            invoice=self.inv, amount=self.inv.total, approval_request=req, method="bank"
        )
        p2 = record_payment(
            invoice=self.inv, amount=self.inv.total, approval_request=req, method="bank"
        )
        self.assertEqual(p1.pk, p2.pk)
        self.assertEqual(Payment.objects.filter(invoice=self.inv).count(), 1)

    def test_pending_approval_rejected(self):
        req = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.accountant,
            entity=self.inv,
            payload={"invoice_id": self.inv.pk, "amount": str(self.inv.total)},
        )
        with self.assertRaises(DomainError):
            record_payment(
                invoice=self.inv, amount=self.inv.total, approval_request=req, method="bank"
            )

    def test_rejected_approval_rejected(self):
        req = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.accountant,
            entity=self.inv,
            payload={"invoice_id": self.inv.pk, "amount": str(self.inv.total)},
        )
        ApprovalService.decide(req, approved=False, decided_by=self.manager)
        with self.assertRaises(DomainError):
            record_payment(
                invoice=self.inv, amount=self.inv.total, approval_request=req, method="bank"
            )

    def test_wrong_invoice_approval_rejected(self):
        other_charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="Other",
            amount=Decimal("50.00"),
            currency="AZN",
        )
        other = generate_invoice_from_charges(self.party, [other_charge.pk], apply_vat=False)
        confirm_invoice(other)
        req = _approved_pay_req(
            other, other.total, requested_by=self.accountant, decided_by=self.manager
        )
        with self.assertRaises(DomainError):
            record_payment(
                invoice=self.inv, amount=self.inv.total, approval_request=req, method="bank"
            )

    def test_mismatched_amount_rejected(self):
        req = _approved_pay_req(
            self.inv, Decimal("40.00"), requested_by=self.accountant, decided_by=self.manager
        )
        with self.assertRaises(DomainError):
            record_payment(
                invoice=self.inv, amount=Decimal("60.00"), approval_request=req, method="bank"
            )

    def test_missing_approval_arg_typeerror(self):
        with self.assertRaises(TypeError):
            record_payment(invoice=self.inv, amount=self.inv.total, method="bank")

    def test_partial_payments_need_separate_approvals(self):
        r1 = _approved_pay_req(
            self.inv, Decimal("40.00"), requested_by=self.accountant, decided_by=self.manager, reference="P1"
        )
        record_payment(
            invoice=self.inv, amount=Decimal("40.00"), approval_request=r1, method="bank", reference="P1"
        )
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, InvoiceStatus.ISSUED)
        r2 = _approved_pay_req(
            self.inv, Decimal("60.00"), requested_by=self.accountant, decided_by=self.manager, reference="P2"
        )
        record_payment(
            invoice=self.inv, amount=Decimal("60.00"), approval_request=r2, method="bank", reference="P2"
        )
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, InvoiceStatus.PAID)
        self.assertEqual(Payment.objects.filter(invoice=self.inv).count(), 2)
