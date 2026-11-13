from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.crm.access import can_mutate_crm, can_view_crm
from apps.crm.mapping import map_pipeline_stage, map_source, legacy_status_to_fields
from apps.crm.models import (
    Lead,
    Offer,
    OfferStatus,
    Opportunity,
    PipelineStage,
    Qualification,
)
from apps.crm.services import (
    CrmLeadService,
    CrmOfferService,
    CrmOpportunityService,
    LeaseApplicationService,
    find_duplicate_leads,
    scan_lead_activity_reminders,
    scan_offer_followups,
)
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType

User = get_user_model()


class CrmAclTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(
            username="sales1", email="s1@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.admin = User.objects.create_user(
            username="admin1", email="a1@test.az", password="x", role=Role.ADMIN, is_staff=True
        )
        self.reception = User.objects.create_user(
            username="rec1", email="r1@test.az", password="x", role=Role.RECEPTION, is_staff=True
        )
        self.accountant = User.objects.create_user(
            username="acc1", email="c1@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )

    def test_roles(self):
        self.assertTrue(can_view_crm(self.sales))
        self.assertTrue(can_mutate_crm(self.sales))
        self.assertTrue(can_view_crm(self.admin))
        self.assertFalse(can_mutate_crm(self.admin))
        self.assertFalse(can_view_crm(self.reception))
        self.assertTrue(can_view_crm(self.accountant))
        self.assertFalse(can_mutate_crm(self.accountant))

    def test_reception_denied_http(self):
        c = Client()
        c.force_login(self.reception)
        resp = c.get(reverse("erp:crm_leads"))
        # Wrong module → role home, not a dead 403 card
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:reception"))

    def test_sales_can_list(self):
        c = Client()
        c.force_login(self.sales)
        resp = c.get(reverse("erp:crm_leads"))
        self.assertEqual(resp.status_code, 200)


class CrmMappingTests(TestCase):
    def test_source_and_stage(self):
        code, note = map_source("Sosial Şəbəkə")
        self.assertEqual(code, "social_media")
        self.assertEqual(map_pipeline_stage("Təklif göndərilib"), PipelineStage.OFFER_SENT)
        mapped = legacy_status_to_fields("disqualified")
        self.assertEqual(mapped["qualification"], Qualification.NON_POTENTIAL)


class CrmLeadFlowTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(
            username="sales2", email="s2@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.manager = User.objects.create_user(
            username="mgr2", email="m2@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.accountant = User.objects.create_user(
            username="acc2", email="c2@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )

    def test_create_duplicate_and_opportunity(self):
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={"company_name": "Alpha MMC", "phone": "+994501000001", "email": "a@x.az"},
            notify=False,
        )
        dups = find_duplicate_leads(phone="+994501000001", company_name="Alpha")
        self.assertTrue(any(d.pk == lead.pk for d in dups))
        CrmLeadService.update_lead(
            lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
        )
        opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        self.assertEqual(opp.lead_id, lead.pk)
        self.assertEqual(lead.activities.count(), 2)

    def test_offer_send_requires_approval(self):
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={"company_name": "Beta", "phone": "123", "qualification": Qualification.POTENTIAL},
            notify=False,
        )
        CrmLeadService.update_lead(
            lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
        )
        opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        party = Party.objects.create(
            legal_name="Beta MMC",
            party_type=PartyType.ORGANIZATION,
            status=PartyStatus.PROSPECT,
        )
        PartyRole.objects.create(party=party, role=PartyRoleCode.PROSPECT, is_primary=True)
        opp.party = party
        opp.save()
        offer = CrmOfferService.create_offer(
            actor=self.sales, opportunity=opp, party=party, area_m2=Decimal("100")
        )
        version = offer.current_version
        with self.assertRaises(Exception):
            CrmOfferService.send_offer(version, actor=self.sales, sent_to="x@y.az")
        CrmOfferService.request_send_approval(version, actor=self.sales)
        CrmOfferService.decide_approval(version, actor=self.manager, approved=True)
        CrmOfferService.send_offer(version, actor=self.sales, sent_to="x@y.az")
        offer.refresh_from_db()
        self.assertEqual(offer.status, OfferStatus.SENT)

    def test_lease_application_accountant_path(self):
        lead = CrmLeadService.create_lead(
            actor=self.sales, data={"company_name": "Gamma", "phone": "999"}, notify=False
        )
        CrmLeadService.update_lead(
            lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
        )
        opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        party = Party.objects.create(legal_name="Gamma MMC", party_type=PartyType.ORGANIZATION)
        opp.party = party
        opp.save()
        offer = CrmOfferService.create_offer(
            actor=self.sales, opportunity=opp, party=party, area_m2=Decimal("50")
        )
        offer.status = OfferStatus.SENT
        offer.save()
        app = LeaseApplicationService.create_from_offer(
            offer, actor=self.sales, data={"person_name": "Gamma MMC", "tax_id": "1234567890"}
        )
        LeaseApplicationService.submit_to_accounting(app, actor=self.sales)
        LeaseApplicationService.accountant_accept(app, actor=self.accountant)
        LeaseApplicationService.create_lease_draft(app, actor=self.accountant)
        app.refresh_from_db()
        self.assertIsNotNone(app.lease_id)

    def test_reminder_idempotent(self):
        lead = CrmLeadService.create_lead(
            actor=self.sales, data={"company_name": "Idle Co", "phone": "111"}, notify=False
        )
        Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - timedelta(days=2))
        s1 = scan_lead_activity_reminders()
        s2 = scan_lead_activity_reminders()
        self.assertGreaterEqual(s1["reminded"], 1)
        self.assertEqual(s2["reminded"], 0)

        CrmLeadService.update_lead(
            lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
        )
        opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        party = Party.objects.create(legal_name="Idle Party")
        Offer.objects.create(
            opportunity=opp,
            party=party,
            status=OfferStatus.SENT,
            sent_at=timezone.now() - timedelta(days=4),
            rent_amount=0,
        )
        a = scan_offer_followups()
        b = scan_offer_followups()
        self.assertGreaterEqual(a["reminded"], 1)
        self.assertEqual(b["reminded"], 0)
