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
    ActivityType,
    Lead,
    Offer,
    OfferStatus,
    Opportunity,
    Outcome,
    PipelineStage,
    Qualification,
)
from apps.leases.models import LeaseLine
from apps.crm.pdf import build_offer_pdf_bytes
from apps.crm.pipeline import pipeline_strip_counts
from apps.crm.reports import build_crm_funnel_report, build_sales_report, export_crm_xlsx
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
        self.assertFalse(can_view_crm(self.admin))
        self.assertFalse(can_mutate_crm(self.admin))
        self.assertFalse(can_view_crm(self.reception))
        self.assertTrue(can_view_crm(self.accountant))
        self.assertFalse(can_mutate_crm(self.accountant))

    def test_admin_crm_denied_http(self):
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse("erp:crm_leads"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))

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
        # create + qualification STATUS_CHANGE (+ any opp-side notes on lead)
        self.assertGreaterEqual(lead.activities.count(), 2)
        self.assertTrue(
            lead.activities.filter(activity_type=ActivityType.STATUS_CHANGE).exists()
        )

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
        version.refresh_from_db()
        self.assertEqual(offer.status, OfferStatus.SENT)
        self.assertTrue(bool(version.pdf_file))
        pdf = build_offer_pdf_bytes(version)
        self.assertTrue(pdf.startswith(b"%PDF"))

        # Versiya təsdiqli, offer status geridə qalıbsa belə göndərmə işləsin
        offer2 = CrmOfferService.create_offer(
            actor=self.sales, opportunity=opp, party=party, area_m2=Decimal("80")
        )
        version2 = offer2.current_version
        CrmOfferService.request_send_approval(version2, actor=self.sales)
        CrmOfferService.decide_approval(version2, actor=self.manager, approved=True)
        Offer.objects.filter(pk=offer2.pk).update(status=OfferStatus.PENDING_APPROVAL)
        CrmOfferService.send_offer(version2, actor=self.sales, sent_to="z@y.az")
        offer2.refresh_from_db()
        self.assertEqual(offer2.status, OfferStatus.SENT)

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
        self.assertTrue(LeaseLine.objects.filter(lease_id=app.lease_id).exists() or app.lease.space_id is None)
        if app.tax_id:
            self.assertIn(app.tax_id, app.lease.notes)

    def test_lead_update_writes_status_activity(self):
        lead = CrmLeadService.create_lead(
            actor=self.sales, data={"company_name": "Act Co", "phone": "444"}, notify=False
        )
        before = lead.activities.count()
        CrmLeadService.update_lead(
            lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
        )
        self.assertGreater(lead.activities.count(), before)
        self.assertTrue(
            lead.activities.filter(activity_type=ActivityType.STATUS_CHANGE).exists()
        )

    def test_pending_lead_restored_after_duplicate_warn(self):
        CrmLeadService.create_lead(
            actor=self.sales,
            data={"company_name": "Dup Co", "phone": "+994501112233"},
            notify=False,
        )
        client = Client()
        client.force_login(self.sales)
        resp = client.post(
            reverse("erp:crm_leads"),
            {
                "action": "create",
                "company_name": "Dup Co",
                "phone": "+994501112233",
                "email": "dup@test.az",
                "full_name": "Dup Person",
            },
        )
        self.assertEqual(resp.status_code, 302)
        resp = client.get(reverse("erp:crm_leads"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["pending_lead_open"])
        self.assertEqual(resp.context["pending_lead"]["company_name"], "Dup Co")
        self.assertContains(resp, "Dup Co")
        self.assertContains(resp, "value=\"1\" checked", html=False)

    def test_opportunity_lost_and_activity(self):
        lead = CrmLeadService.create_lead(
            actor=self.sales,
            data={"company_name": "Lost Co", "phone": "222", "qualification": Qualification.POTENTIAL},
            notify=False,
        )
        CrmLeadService.update_lead(
            lead, actor=self.sales, data={"qualification": Qualification.POTENTIAL}
        )
        opp = CrmOpportunityService.create_from_lead(lead, actor=self.sales)
        CrmOpportunityService.add_activity(
            opp, actor=self.sales, activity_type="viewing", body="Baxış"
        )
        CrmOpportunityService.set_stage(
            opp,
            actor=self.sales,
            stage=PipelineStage.LOST,
            outcome=Outcome.PRICE,
            contact_channels=["phone", "email"],
        )
        opp.refresh_from_db()
        self.assertEqual(opp.status, "lost")
        self.assertEqual(opp.outcome, Outcome.PRICE)
        self.assertEqual(set(opp.contact_channels), {"phone", "email"})
        self.assertGreaterEqual(opp.activities.count(), 2)

    def test_dual_reports_and_pipeline(self):
        CrmLeadService.create_lead(
            actor=self.sales, data={"company_name": "Rep Co", "phone": "333"}, notify=False
        )
        crm = build_crm_funnel_report({})
        sales = build_sales_report({})
        self.assertIn("lead_count", crm)
        self.assertIn("opportunity_count", sales)
        xlsx = export_crm_xlsx({}, tab="crm")
        self.assertTrue(len(xlsx) > 100)
        xlsx2 = export_crm_xlsx({}, tab="sales")
        self.assertTrue(len(xlsx2) > 100)
        steps = pipeline_strip_counts()
        self.assertEqual(len(steps), 4)
        self.assertEqual(steps[0]["key"], "leads")

    def test_reminder_idempotent(self):
        lead = CrmLeadService.create_lead(
            actor=self.sales, data={"company_name": "Idle Co", "phone": "111"}, notify=False
        )
        # 24 iş saatı — bir neçə təqvim günü ehtiyatı
        Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - timedelta(days=5))
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
