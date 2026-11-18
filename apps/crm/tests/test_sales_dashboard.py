"""Satış paneli — rol branch, ops KPI yox, CRM KPI bəli."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.routing import home_url_name_for
from apps.crm.dashboard import build_sales_dashboard, open_leads_qs, parse_period
from apps.crm.models import (
    Lead,
    LeaseApplication,
    LeaseApplicationStatus,
    Offer,
    OfferStatus,
    Opportunity,
    OpportunityStatus,
    PipelineStage,
    Qualification,
    RecordStatus,
)
from apps.parties.models import Party, PartyStatus, PartyType
from apps.property.models import (
    Building,
    CommercialStatus,
    Floor,
    Occupancy,
    OperationalStatus,
    Space,
)

User = get_user_model()


class SalesDashboardRoutingTests(TestCase):
    def test_sales_home_is_dashboard(self):
        u = User.objects.create_user(
            username="sales_home", email="sh@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.assertEqual(home_url_name_for(u), "erp:dashboard")


class SalesDashboardViewTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(
            username="sales_dash", email="sd@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.admin = User.objects.create_user(
            username="admin_dash", email="ad@test.az", password="x", role=Role.ADMIN, is_staff=True
        )
        self.mgmt = User.objects.create_user(
            username="mgmt_dash", email="md@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )

    def test_sales_sees_sales_panel_not_ops(self):
        Lead.objects.create(
            company_name="Acme",
            full_name="A",
            record_status=RecordStatus.OPEN,
            qualification=Qualification.POTENTIAL,
            created_by=self.sales,
        )
        c = Client()
        c.force_login(self.sales)
        resp = c.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_sales_dashboard"])
        self.assertContains(resp, "Satış paneli")
        self.assertNotContains(resp, "QONAQLAR")
        self.assertNotContains(resp, "SLA RİSKİ")
        self.assertNotContains(resp, "İÇƏRİDƏ")
        self.assertNotIn("guest_count", resp.context)
        self.assertNotIn("sla_risk_count", resp.context)
        self.assertNotIn("people_inside_count", resp.context)
        self.assertNotIn("new_residents", resp.context)
        self.assertIn("kpi", resp.context)
        self.assertEqual(resp.context["kpi"]["open_leads"]["count"], 1)
        self.assertFalse(resp.context.get("can_approve_offer"))

    def test_admin_keeps_ops_panel(self):
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["is_sales_dashboard"])
        self.assertContains(resp, "İdarə paneli")
        self.assertContains(resp, "QONAQLAR")
        self.assertIn("guest_count", resp.context)

    def test_management_keeps_ops_panel(self):
        c = Client()
        c.force_login(self.mgmt)
        resp = c.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["is_sales_dashboard"])
        self.assertIn("guest_count", resp.context)


class SalesDashboardHelperTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(
            username="sales_h", email="sh2@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.party = Party.objects.create(
            legal_name="Party Co",
            party_type=PartyType.ORGANIZATION,
            status=PartyStatus.PROSPECT,
        )

    def test_open_leads_excludes_non_potential_and_closed(self):
        Lead.objects.create(
            company_name="Open",
            record_status=RecordStatus.OPEN,
            qualification=Qualification.POTENTIAL,
        )
        Lead.objects.create(
            company_name="NP",
            record_status=RecordStatus.OPEN,
            qualification=Qualification.NON_POTENTIAL,
        )
        Lead.objects.create(
            company_name="Closed",
            record_status=RecordStatus.CLOSED,
            qualification=Qualification.POTENTIAL,
        )
        Lead.objects.create(
            company_name="Won",
            record_status=RecordStatus.OPEN,
            qualification=Qualification.POTENTIAL,
            pipeline_stage=PipelineStage.WON,
        )
        self.assertEqual(open_leads_qs().count(), 1)

    def test_period_events_use_sent_at_not_status(self):
        opp = Opportunity.objects.create(title="O1", status=OpportunityStatus.OPEN, party=self.party)
        Offer.objects.create(
            opportunity=opp,
            party=self.party,
            status=OfferStatus.SENT,
            sent_at=timezone.now(),
        )
        Offer.objects.create(
            opportunity=opp,
            party=self.party,
            status=OfferStatus.SENT,
            sent_at=None,
        )
        data = build_sales_dashboard(self.sales, {"period": "month"})
        self.assertEqual(data["period_events"]["offers_sent"], 1)
        self.assertFalse(data["period_events"]["show_win_loss"])
        self.assertFalse(data["period_events"]["show_conversion"])

    def test_applications_attention_excludes_accountant_queue(self):
        opp = Opportunity.objects.create(title="O2", status=OpportunityStatus.OPEN)
        LeaseApplication.objects.create(
            opportunity=opp,
            status=LeaseApplicationStatus.DRAFT,
            person_name="Draft Co",
        )
        LeaseApplication.objects.create(
            opportunity=opp,
            status=LeaseApplicationStatus.SUBMITTED_TO_ACCOUNTING,
            person_name="Acc Co",
        )
        LeaseApplication.objects.create(
            opportunity=opp,
            status=LeaseApplicationStatus.RETURNED_FOR_CORRECTION,
            person_name="Fix Co",
        )
        data = build_sales_dashboard(self.sales, {})
        titles = {r["title"] for r in data["attention_applications"]}
        self.assertIn("Draft Co", titles)
        self.assertIn("Fix Co", titles)
        self.assertNotIn("Acc Co", titles)
        self.assertEqual(data["kpi"]["applications"]["sales_work"], 2)
        self.assertEqual(data["kpi"]["applications"]["accountant_queue"], 1)

    def test_available_spaces_excludes_active_lease_hold(self):
        b = Building.objects.create(code="CPD", name="CP Dash")
        fl = Floor.objects.create(building=b, code="F1", name="1")
        free = Space.objects.create(
            code="FREE-1",
            floor=fl,
            area_m2=Decimal("50"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.VACANT,
        )
        held = Space.objects.create(
            code="HELD-1",
            floor=fl,
            area_m2=Decimal("80"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.ACTIVE_LEASE,
        )
        data = build_sales_dashboard(self.sales, {})
        self.assertTrue(data["kpi"]["available_spaces"]["show"])
        self.assertGreaterEqual(data["kpi"]["available_spaces"]["count"], 1)
        self.assertNotIn("available_space_rows", data)

    def test_parse_period_custom(self):
        p = parse_period({"period": "custom", "date_from": "2026-01-10", "date_to": "2026-01-05"})
        self.assertEqual(p["key"], "custom")
        self.assertEqual(str(p["date_from"]), "2026-01-05")
        self.assertEqual(str(p["date_to"]), "2026-01-10")

    def test_kpi_offer_links(self):
        data = build_sales_dashboard(self.sales, {})
        self.assertIn("status=pending_approval", data["kpi"]["offers_action"]["url_pending"])
        self.assertIn("/erp/crm/leads/", data["kpi"]["open_leads"]["url"])
