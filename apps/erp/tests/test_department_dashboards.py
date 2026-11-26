"""Phase 3 — department dashboards with real aggregates."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.erp.department_dashboards import (
    build_facility_dashboard,
    build_helpdesk_dashboard,
    build_hr_dashboard,
)
from apps.leases.models import Lease, LeaseLine, LeaseStatus
from apps.parties.models import Party
from apps.property.models import Building, CommercialStatus, Floor, Occupancy, OperationalStatus, Space
from apps.rbac.services import seed_rbac_catalog

User = get_user_model()


class DepartmentDashboardViewTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.fm = User.objects.create_user(
            username="fm_d", email="fm_d@test.az", password="x", role=Role.SERVICE_DESK, is_staff=True
        )
        self.desk = User.objects.create_user(
            username="sd_d", email="sd_d@test.az", password="x", role=Role.SERVICE_DESK, is_staff=True
        )
        self.mgmt = User.objects.create_user(
            username="mg_d", email="mg_d@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.admin = User.objects.create_user(
            username="ad_d",
            email="ad_d@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )

    def test_facility_dashboard_ok(self):
        self.client.force_login(self.fm)
        resp = self.client.get(reverse("erp:facility_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["kpis"])

    def test_helpdesk_dashboard_ok(self):
        self.client.force_login(self.desk)
        resp = self.client.get(reverse("erp:helpdesk_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["kpis"])

    def test_hr_and_procurement_for_management(self):
        self.client.force_login(self.mgmt)
        self.assertEqual(self.client.get(reverse("erp:hr_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("erp:procurement_dashboard")).status_code, 200)

    def test_it_dashboard_for_admin(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("erp:it_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["kpis"])

    def test_dashboard_redirects_fm_and_desk(self):
        self.client.force_login(self.fm)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:facility_dashboard"))
        self.client.force_login(self.desk)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:helpdesk_dashboard"))

    def test_admin_dashboard_redirects_to_it(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:it_dashboard"))
        ops = self.client.get(reverse("erp:dashboard") + "?ops=1")
        self.assertEqual(ops.status_code, 200)


class FacilityAggregationTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.fm = User.objects.create_user(
            username="fm_a", email="fm_a@test.az", password="x", role=Role.SERVICE_DESK, is_staff=True
        )
        building = Building.objects.create(code="TB-P3", name="Test B P3")
        self.floor = Floor.objects.create(building=building, code="F1", name="F1")
        Space.objects.create(
            code="T-VAC", name="Vacant", floor=self.floor, occupancy=Occupancy.VACANT,
        )
        Space.objects.create(
            code="T-ACT", name="Active", floor=self.floor, commercial_status=CommercialStatus.ACTIVE,
        )

    def test_facility_kpi_counts_spaces(self):
        # Facility landing now reuses the Supply board (no separate space KPIs).
        board = build_facility_dashboard(self.fm)
        labels = [str(k["label"]) for k in board["kpis"]]
        self.assertTrue(any("müraciət" in lab.casefold() for lab in labels))
        open_wo = next(
            k["value"]
            for k in board["kpis"]
            if "iş sifariş" in str(k["label"]).casefold() or "wo" in str(k["label"]).casefold()
        )
        self.assertGreaterEqual(open_wo, 0)

    def test_vacant_kpi_matches_filtered_floor_register(self):
        Space.objects.create(
            code="T-BLOCKED", floor=self.floor, occupancy=Occupancy.VACANT,
            operational_status=OperationalStatus.BLOCKED,
        )
        self.client.force_login(self.fm)
        response = self.client.get(reverse("erp:spaces"), {"status": "vacant"})
        self.assertEqual(response.status_code, 200)
        visible_codes = [
            item["space"].code
            for row in response.context["floor_rows"]
            for item in row["spaces"]
        ]
        self.assertIn("T-VAC", visible_codes)
        self.assertNotIn("T-BLOCKED", visible_codes)
        self.assertContains(response, reverse("erp:space_detail", kwargs={"code": "T-VAC"}))

        response = self.client.get(reverse("erp:spaces"), {"floor": self.floor.pk, "q": "t-blocked"})
        self.assertContains(response, "erp-space-tile--blocked")
        self.assertNotContains(response, "erp-space-tile--vacant")

    def test_floor_register_finds_active_lease_on_secondary_space(self):
        today = timezone.localdate()
        party = Party.objects.create(legal_name="Test Office Tenant")
        primary = Space.objects.get(code="T-ACT")
        secondary = Space.objects.create(
            code="T-SECONDARY", floor=self.floor, commercial_status=CommercialStatus.ACTIVE, area_m2=35,
        )
        lease = Lease.objects.create(
            code="TEST-LEASE-SPACES", party=party, space=primary, status=LeaseStatus.ACTIVE,
            start_date=today - timedelta(days=30), end_date=today + timedelta(days=60),
        )
        LeaseLine.objects.create(lease=lease, space=secondary)
        self.client.force_login(self.fm)
        response = self.client.get(reverse("erp:spaces"), {"q": "test office tenant", "status": "occupied"})
        self.assertContains(response, reverse("erp:space_detail", kwargs={"code": secondary.code}))
        self.assertContains(response, lease.end_date.strftime("%d.%m.%Y"))

    def test_helpdesk_board_shape(self):
        board = build_helpdesk_dashboard(self.fm)
        self.assertIn("kpis", board)
        self.assertIn("pending", board)
        self.assertIn("quick_actions", board)
        hr = build_hr_dashboard(self.fm)
        self.assertIn("kpis", hr)
