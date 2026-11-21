from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.accounting.models import JournalEntry
from apps.accounting.services import AccountingService
from apps.billing.models import Charge, ChargeSource, InvoiceStatus, Payment
from apps.billing.services import (
    confirm_invoice,
    generate_invoice_from_charges,
    record_payment,
    void_invoice,
)
from apps.parties.models import Party, PartyStatus, PartyType
from apps.parties.resolvers import party_for_company
from apps.residents.models import ResidentCompany
from apps.workflows.services import ApprovalService

User = get_user_model()


class M10BillingAccountingTests(TestCase):
    def setUp(self):
        self.party = Party.objects.create(
            party_type=PartyType.ORGANIZATION,
            legal_name="M10 Co",
            status=PartyStatus.ACTIVE,
        )
        self.accountant = User.objects.create_user(
            username="m10-acct",
            email="m10-acct@test.az",
            password="Pass12345!",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="m10-mgmt",
            email="m10-mgmt@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )

    def _draft_confirmed(self, amount="100.00"):
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="M10 rent",
            amount=Decimal(amount),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        return inv

    def _approved_req(self, inv, amount, reference=""):
        req = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.accountant,
            entity=inv,
            payload={
                "invoice_id": inv.pk,
                "invoice_code": inv.code,
                "amount": str(amount),
                "method": "bank",
                "reference": reference,
            },
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        req.refresh_from_db()
        return req

    def test_journal_from_invoice_idempotent(self):
        inv = self._draft_confirmed()
        je1 = AccountingService.journal_from_invoice(inv, net=inv.total, vat=0)
        je2 = AccountingService.journal_from_invoice(inv, net=inv.total, vat=0)
        self.assertEqual(je1.pk, je2.pk)
        self.assertEqual(
            JournalEntry.objects.filter(source="billing.invoice", source_ref=f"invoice:{inv.pk}").count(),
            1,
        )

    def test_journal_splits_revenue_by_charge_source(self):
        from apps.accounting.coa import code_for
        from apps.accounting.models import JournalLine

        rent = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="Rent split",
            amount=Decimal("80.00"),
            currency="AZN",
        )
        sc = Charge.objects.create(
            party=self.party,
            source=ChargeSource.SERVICE_CHARGE,
            description="SC split",
            amount=Decimal("20.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [rent.pk, sc.pk], apply_vat=False)
        confirm_invoice(inv)
        je = JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv.pk}")
        by_acct = {
            ln.account.code: ln.credit
            for ln in JournalLine.objects.filter(entry=je).select_related("account")
            if ln.credit
        }
        self.assertEqual(by_acct.get(code_for("rent_revenue")), Decimal("80.00"))
        self.assertEqual(by_acct.get(code_for("service_revenue")), Decimal("20.00"))

    def test_partial_then_full_payment_matches_party(self):
        inv = self._draft_confirmed("100.00")
        r1 = self._approved_req(inv, Decimal("40.00"), reference="REF-1")
        p1 = record_payment(
            invoice=inv,
            amount=Decimal("40.00"),
            method="bank",
            reference="REF-1",
            approval_request=r1,
        )
        self.assertEqual(p1.party_id, self.party.pk)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.ISSUED)
        r2 = self._approved_req(inv, Decimal("60.00"), reference="REF-2")
        p2 = record_payment(
            invoice=inv,
            amount=Decimal("60.00"),
            method="bank",
            reference="REF-2",
            approval_request=r2,
        )
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.PAID)
        self.assertEqual(Payment.objects.filter(invoice=inv).count(), 2)
        self.assertEqual(
            JournalEntry.objects.filter(source="billing.payment", source_ref=f"payment:{p2.pk}").count(),
            1,
        )

    def test_void_reverses_journal_and_unlinks_charges(self):
        inv = self._draft_confirmed()
        charge = Charge.objects.get(invoice=inv)
        je = JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv.pk}")
        void_invoice(inv, actor=self.accountant)
        inv.refresh_from_db()
        charge.refresh_from_db()
        je.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.VOID)
        self.assertIsNone(charge.invoice_id)
        self.assertIsNotNone(je.reversed_entry_id)

    def test_reverse_journal_idempotent(self):
        inv = self._draft_confirmed()
        je = JournalEntry.objects.get(source="billing.invoice", source_ref=f"invoice:{inv.pk}")
        r1 = AccountingService.reverse_journal(je, actor=self.accountant)
        r2 = AccountingService.reverse_journal(je, actor=self.accountant)
        self.assertEqual(r1.pk, r2.pk)

    def test_inactive_account_rejected(self):
        from apps.accounting.models import Account
        from apps.accounting.services import seed_minimal_coa
        from apps.core.services import DomainError

        seed_minimal_coa()
        acct = Account.objects.get(code="101")
        acct.is_active = False
        acct.save(update_fields=["is_active"])
        with self.assertRaises(DomainError):
            AccountingService.post_journal(
                lines=[
                    {"account_code": "101", "debit": Decimal("1"), "credit": 0},
                    {"account_code": "400", "debit": 0, "credit": Decimal("1")},
                ],
                memo="inactive",
            )


class PortalInvoicesTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="Portal Fin", slug="portal-fin", portal_active=True
        )
        self.party = party_for_company(self.company, ensure=True)
        self.user = User.objects.create_user(
            username="portal-fin",
            email="portal-fin@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        ensure_portal_membership(self.user, self.company)
        self.client = Client()
        self.client.force_login(self.user)
        self.client.post(reverse("portal:choose_companies"), {"choice": str(self.company.pk)})

    def test_portal_shows_issued_balance(self):
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="Portal rent",
            amount=Decimal("50.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk], apply_vat=False)
        confirm_invoice(inv)
        resp = self.client.get(reverse("portal:invoices"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, inv.code)
        self.assertContains(resp, "50")
