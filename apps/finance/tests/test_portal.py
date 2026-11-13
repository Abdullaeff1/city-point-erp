from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounting.models import JournalEntry
from apps.accounting.services import AccountingService
from apps.billing.models import Charge, ChargeSource, InvoiceStatus
from apps.billing.policy import DUE_DAYS, INVOICE_WINDOW_DAYS, due_date_for, in_invoice_window, vat_breakdown
from apps.billing.services import (
    apply_penalty_charge,
    confirm_invoice,
    generate_invoice_from_charges,
    record_payment,
)
from apps.core.services import DomainError
from apps.leases.lease_ops import generate_monthly_lease_charges, prorata_factor
from apps.leases.models import Lease, LeaseStatus
from apps.parties.models import Party
from apps.property.models import Building, Floor, Space
from apps.workflows.services import ApprovalService

User = get_user_model()


class FinancePortalAclTests(TestCase):
    def setUp(self):
        self.accountant = User.objects.create_user(
            username="acct1",
            email="accountant@test.az",
            password="Pass12345!",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="mgr1",
            email="manager@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="adm1",
            email="admin-fin@test.az",
            password="Pass12345!",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.client = Client()

    def test_accountant_login_lands_on_finance_home(self):
        self.client.force_login(self.accountant)
        resp = self.client.get(reverse("post_login"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("finance:home"))

    def test_accountant_and_manager_ok_admin_denied(self):
        self.client.force_login(self.accountant)
        self.assertEqual(self.client.get(reverse("finance:home")).status_code, 200)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("finance:home")).status_code, 200)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("finance:home"))
        # Wrong portal → redirect to ERP home (no dead 403 card)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))

    def test_accountant_erp_redirects_to_finance(self):
        self.assertFalse(self.accountant.can_access_erp())
        self.client.force_login(self.accountant)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("finance:home"))


class FinanceArGlTests(TestCase):
    def setUp(self):
        self.accountant = User.objects.create_user(
            username="acct2",
            email="accountant2@test.az",
            password="Pass12345!",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.manager = User.objects.create_user(
            username="mgr2",
            email="manager2@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.party = Party.objects.create(legal_name="Fin Co")
        building = Building.objects.create(code="B1", name="B1")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        self.space = Space.objects.create(
            code="S1",
            name="S1",
            floor=floor,
            area_m2=Decimal("100"),
            rentable_area_m2=Decimal("100"),
            base_rent_rate=Decimal("10"),
            service_charge_rate=Decimal("2"),
        )
        self.lease = Lease.objects.create(
            code="LS-T1",
            party=self.party,
            space=self.space,
            status=LeaseStatus.ACTIVE,
            billing_active=True,
            start_date=date(2026, 11, 1),
            rent_rate_per_m2=Decimal("10"),
            service_rate_per_m2=Decimal("2"),
            rent=Decimal("1000"),
            service_charge=Decimal("200"),
            deposit_months=2,
            parking_included_free=True,
        )
        self.client = Client()
        self.client.force_login(self.accountant)

    def test_policy_due_and_window(self):
        self.assertEqual(DUE_DAYS, 30)
        self.assertEqual(INVOICE_WINDOW_DAYS, 5)
        issue = date(2026, 11, 3)
        self.assertEqual(due_date_for(issue), date(2026, 12, 3))
        self.assertTrue(in_invoice_window(date(2026, 11, 3)))
        self.assertFalse(in_invoice_window(date(2026, 11, 10)))
        br = vat_breakdown(Decimal("100"))
        self.assertEqual(br["vat"], Decimal("18.00"))
        self.assertEqual(br["gross"], Decimal("118.00"))

    def test_prorata_and_m2_charges(self):
        self.assertEqual(
            prorata_factor(
                period_start=date(2026, 11, 1),
                period_end=date(2026, 11, 30),
                lease_start=date(2026, 11, 16),
            ),
            Decimal("0.5000"),
        )
        self.lease.start_date = date(2026, 11, 1)
        self.lease.save()
        stats = generate_monthly_lease_charges(as_of=date(2026, 11, 5))
        self.assertGreaterEqual(stats["created"], 2)
        rent = Charge.objects.get(lease=self.lease, source=ChargeSource.RENT)
        self.assertEqual(rent.amount, Decimal("1000.00"))
        self.assertFalse(
            Charge.objects.filter(lease=self.lease, source=ChargeSource.PARKING).exists()
        )

    def test_draft_confirm_and_unposted_je(self):
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="Rent test",
            amount=Decimal("100.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk])
        self.assertEqual(inv.status, InvoiceStatus.DRAFT)
        self.assertEqual(inv.total, Decimal("118.00"))
        confirm_invoice(inv)
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.ISSUED)
        self.assertEqual((inv.due_date - inv.issue_date).days, DUE_DAYS)
        je = JournalEntry.objects.filter(source="billing.invoice").latest("id")
        self.assertFalse(je.posted)
        AccountingService.post_to_gl(je)
        je.refresh_from_db()
        self.assertTrue(je.posted)

    def test_manual_penalty_and_payment_approval(self):
        charge = Charge.objects.create(
            party=self.party,
            source=ChargeSource.RENT,
            description="Rent pay",
            amount=Decimal("50.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(self.party, [charge.pk])
        confirm_invoice(inv)
        apply_penalty_charge(inv, amount=Decimal("12.50"), description="Late fee")
        self.assertTrue(
            Charge.objects.filter(source=ChargeSource.PENALTY, amount=Decimal("12.50")).exists()
        )
        req = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.accountant,
            entity=inv,
            payload={
                "invoice_id": inv.pk,
                "invoice_code": inv.code,
                "amount": str(inv.total),
                "method": "bank",
                "reference": "T1",
            },
        )
        ApprovalService.decide(req, approved=True, decided_by=self.manager)
        record_payment(invoice=inv, amount=inv.total, method="bank", reference="T1")
        inv.refresh_from_db()
        self.assertEqual(inv.status, InvoiceStatus.PAID)
        pay_je = JournalEntry.objects.filter(source="billing.payment").latest("id")
        self.assertFalse(pay_je.posted)

    def test_period_close_blocks_journal(self):
        today = timezone.localdate()
        AccountingService.close_period(year=today.year, month=today.month, actor=self.accountant)
        with self.assertRaises(DomainError):
            AccountingService.post_journal(
                lines=[
                    {"account_code": "101", "debit": Decimal("1"), "credit": 0},
                    {"account_code": "400", "debit": 0, "credit": Decimal("1")},
                ],
                memo="blocked",
            )

    def test_pages_and_exports(self):
        for name in (
            "finance:home",
            "finance:charges",
            "finance:invoices",
            "finance:payments",
            "finance:accounts",
            "finance:journals",
            "finance:journal_create",
            "finance:trial_balance",
            "finance:periods",
            "finance:aging",
        ):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, name)
        self.assertEqual(self.client.get(reverse("finance:aging_export")).status_code, 200)
        self.assertEqual(self.client.get(reverse("finance:invoices_export")).status_code, 200)
        self.assertEqual(self.client.get(reverse("finance:trial_balance_export")).status_code, 200)

    def test_manager_cannot_mutate_charges(self):
        self.client.force_login(self.manager)
        resp = self.client.post(
            reverse("finance:charges"),
            {"action": "generate_lease_charges"},
        )
        self.assertEqual(resp.status_code, 302)
        # no new charges from manager
        before = Charge.objects.count()
        self.assertEqual(Charge.objects.count(), before)
