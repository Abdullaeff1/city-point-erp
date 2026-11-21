from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.billing.models import Charge, ChargeSource, InvoiceStatus
from apps.billing.services import confirm_invoice, generate_invoice_from_charges, record_payment
from apps.core.services import DomainError
from apps.parties.models import Party, PartyStatus, PartyType
from apps.workflows.services import ApprovalService

User = get_user_model()


class BillingHardeningTests(TestCase):
    def setUp(self):
        self.party = Party.objects.create(
            party_type=PartyType.ORGANIZATION,
            legal_name="Bill Co",
            status=PartyStatus.ACTIVE,
        )
        self.accountant = User.objects.create_user(
            username="bill-acc", email="bill-acc@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.manager = User.objects.create_user(
            username="bill-mgmt", email="bill-mgmt@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )

    def test_confirm_invoice_surfaces_journal_failure(self):
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="Rent",
            amount=Decimal("10.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        with patch(
            "apps.accounting.services.AccountingService.journal_from_invoice",
            side_effect=RuntimeError("coa broken"),
        ):
            with self.assertRaises(DomainError):
                confirm_invoice(inv)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.DRAFT)

    def test_record_payment_surfaces_journal_failure(self):
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="Rent pay",
            amount=Decimal("10.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        req = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.accountant,
            entity=inv,
            payload={"invoice_id": inv.pk, "amount": str(inv.total), "method": "bank"},
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        req.refresh_from_db()
        with patch(
            "apps.accounting.services.AccountingService.journal_from_payment",
            side_effect=RuntimeError("je fail"),
        ):
            with self.assertRaises(DomainError):
                record_payment(
                    invoice=inv, amount=inv.total, method="bank", approval_request=req
                )
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.ISSUED)
        self.assertEqual(inv.payments.count(), 0)
        req.refresh_from_db()
        # Atomic rollback: approval remains APPROVED but unconsumed for retry
        self.assertIsNone((req.payload or {}).get("payment_id"))

    def test_invoice_codes_unique_sequence(self):
        ids = []
        for i in range(3):
            c = Charge.objects.create(
                party=self.party,
                source=ChargeSource.RENT,
                description=f"R{i}",
                amount=Decimal("1.00"),
                currency="AZN",
            )
            inv = generate_invoice_from_charges(self.party, [c.pk], apply_vat=False)
            ids.append(inv.code)
        self.assertEqual(len(ids), len(set(ids)))
        nums = [int(c.split("-")[1]) for c in ids]
        self.assertEqual(nums, sorted(nums))
        self.assertEqual(nums[-1] - nums[0], 2)
