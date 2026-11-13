from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.billing.models import Charge, ChargeSource
from apps.billing.services import confirm_invoice, generate_invoice_from_charges
from apps.crm.access import can_mutate_crm, can_view_crm
from apps.crm.models import Lead, OfferStatus, Qualification
from apps.crm.services import CrmLeadService, CrmOfferService, CrmOpportunityService
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType
from apps.workflows.models import ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class ManagementErpAclTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="mgmt-p",
            email="manager-portal@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="sales-p",
            email="sales-portal@test.az",
            password="Pass12345!",
            role=Role.SALES,
            is_staff=True,
        )
        self.accountant = User.objects.create_user(
            username="acct-p",
            email="acct-portal@test.az",
            password="Pass12345!",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="adm-p",
            email="admin-portal@test.az",
            password="Pass12345!",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.client = Client()

    def test_manager_login_lands_on_erp(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("post_login"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))

    def test_manager_erp_ok(self):
        self.assertTrue(self.manager.can_access_erp())
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("erp:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("erp:approvals")).status_code, 200)
        self.assertEqual(self.client.get(reverse("erp:payment_approvals")).status_code, 200)
        self.assertEqual(self.client.get(reverse("erp:ar_aging")).status_code, 200)
        self.assertEqual(self.client.get(reverse("erp:accounting_periods")).status_code, 200)

    def test_legacy_management_urls_redirect(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("management:home"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))
        resp2 = self.client.get(reverse("management:approvals"))
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(resp2.url, reverse("erp:approvals"))

    def test_manager_crm_view_no_mutate(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("erp:crm_leads"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["can_mutate"])
        create = self.client.post(
            reverse("erp:crm_leads"),
            {"action": "create", "company_name": "Blocked Co", "phone": "100"},
        )
        self.assertEqual(create.status_code, 302)
        self.assertEqual(create.url, reverse("erp:crm_leads"))
        self.assertFalse(Lead.objects.filter(company_name="Blocked Co").exists())

    def test_sales_and_accountant_denied_approvals(self):
        self.client.force_login(self.sales)
        resp = self.client.get(reverse("erp:approvals"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:crm_leads"))
        self.client.force_login(self.accountant)
        resp = self.client.get(reverse("erp:approvals"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("finance:home"))

    def test_sales_mutates_manager_does_not(self):
        self.assertTrue(can_view_crm(self.manager))
        self.assertFalse(can_mutate_crm(self.manager))
        self.assertTrue(can_mutate_crm(self.sales))


class ManagementApprovalFlowTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="mgmt-a",
            email="manager-appr@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="sales-a",
            email="sales-appr@test.az",
            password="Pass12345!",
            role=Role.SALES,
            is_staff=True,
        )
        self.accountant = User.objects.create_user(
            username="acct-a",
            email="acct-appr@test.az",
            password="Pass12345!",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.client = Client()

    def _offer_pending(self):
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={
                "company_name": "Portal Offer Co",
                "phone": "555001",
                "qualification": Qualification.POTENTIAL,
            },
            notify=False,
        )
        CrmLeadService.update_lead(
            lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
        )
        opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        party = Party.objects.create(
            legal_name="Portal Offer Co",
            party_type=PartyType.ORGANIZATION,
            status=PartyStatus.PROSPECT,
        )
        PartyRole.objects.create(party=party, role=PartyRoleCode.PROSPECT, is_primary=True)
        opp.party = party
        opp.save()
        offer = CrmOfferService.create_offer(
            actor=self.sales, opportunity=opp, party=party, area_m2=Decimal("80")
        )
        version = offer.current_version
        CrmOfferService.request_send_approval(version, actor=self.sales)
        return offer, version

    def test_offer_approval_from_erp(self):
        offer, version = self._offer_pending()
        req = version.approval_request
        self.assertEqual(req.status, ApprovalStatus.PENDING)
        self.client.force_login(self.manager)
        resp = self.client.post(
            reverse("erp:approvals"),
            {"approval_id": req.pk, "action": "approve", "comment": "ok"},
        )
        self.assertEqual(resp.status_code, 302)
        offer.refresh_from_db()
        self.assertEqual(offer.status, OfferStatus.APPROVED)

    def test_payment_approval_from_erp(self):
        party = Party.objects.create(legal_name="Pay Co")
        charge = Charge.objects.create(
            party=party,
            source=ChargeSource.RENT,
            description="Rent",
            amount=Decimal("100.00"),
            currency="AZN",
        )
        inv = generate_invoice_from_charges(party, [charge.pk])
        confirm_invoice(inv)
        req = ApprovalService.request(
            workflow_code="finance.payment",
            requested_by=self.accountant,
            entity=inv,
            payload={
                "invoice_id": inv.pk,
                "invoice_code": inv.code,
                "amount": str(inv.total),
                "method": "bank",
                "reference": "MGMT1",
            },
        )
        self.client.force_login(self.manager)
        resp = self.client.post(
            reverse("erp:payment_approvals"),
            {"action": "approve_pay", "approval_id": req.pk},
        )
        self.assertEqual(resp.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.APPROVED)
        inv.refresh_from_db()
        self.assertTrue(inv.payments.exists())
