from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.billing.models import Invoice, InvoiceStatus
from apps.finance.dashboard import build_dashboard, draft_invoices_qs, pending_payment_approvals_qs
from apps.parties.models import Party, PartyType

User = get_user_model()


class DashboardKpiReconcileTests(TestCase):
    def setUp(self):
        self.accountant = User.objects.create_user(
            username="dash-acct",
            email="dash-acct@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.party = Party.objects.create(
            legal_name="Dash Co", party_type=PartyType.ORGANIZATION
        )
        self.client = Client()

    def test_draft_card_matches_invoice_filter(self):
        Invoice.objects.create(
            code="INV-DASH-1", party=self.party, status=InvoiceStatus.DRAFT, total=10
        )
        Invoice.objects.create(
            code="INV-DASH-2", party=self.party, status=InvoiceStatus.ISSUED, total=20
        )
        dash = build_dashboard()
        draft_card = next(c for c in dash["queue"] if c["key"] == "draft")
        self.assertEqual(draft_card["count"], draft_invoices_qs().count())
        self.assertEqual(draft_card["count"], 1)
        self.client.force_login(self.accountant)
        home = self.client.get(reverse("finance:home"))
        self.assertEqual(home.status_code, 200)
        filtered = self.client.get(reverse("finance:invoices"), {"status": "draft"})
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.context["invoices"].count(), draft_card["count"])

    def test_pending_approvals_inspect_without_approve_for_accountant(self):
        self.assertEqual(pending_payment_approvals_qs().count(), 0)
        self.client.force_login(self.accountant)
        page = self.client.get(reverse("finance:payments"), {"pending": "1"})
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context["pending_only"])
        self.assertFalse(page.context["can_approve"])
        self.assertContains(page, "təsdiq yalnız rəhbərlikdədir", status_code=200)
