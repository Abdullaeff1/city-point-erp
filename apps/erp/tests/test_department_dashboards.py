"""Phase 3 — department dashboards with real aggregates."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.erp.department_dashboards import (
    build_facility_dashboard,
    build_helpdesk_dashboard,
    build_hr_dashboard,
)
from apps.property.models import Building, CommercialStatus, Floor, Space
from apps.rbac.services import seed_rbac_catalog

User = get_user_model()


class DepartmentDashboardViewTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.fm = User.objects.create_user(
            username="fm_d", email="fm_d@test.az", password="x", role=Role.PROPERTY_FM, is_staff=True
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
            username="fm_a", email="fm_a@test.az", password="x", role=Role.PROPERTY_FM, is_staff=True
        )
        building = Building.objects.create(code="TB-P3", name="Test B P3")
        floor = Floor.objects.create(building=building, code="F1", name="F1")
        Space.objects.create(
            code="T-VAC", name="Vacant", floor=floor, commercial_status=CommercialStatus.VACANT
        )
        Space.objects.create(
            code="T-ACT", name="Active", floor=floor, commercial_status=CommercialStatus.ACTIVE
        )

    def test_facility_kpi_counts_spaces(self):
        board = build_facility_dashboard(self.fm)
        vacant = next(k["value"] for k in board["kpis"] if "Boş" in str(k["label"]))
        self.assertGreaterEqual(vacant, 1)
        occupied = next(k["value"] for k in board["kpis"] if "Məşğul" in str(k["label"]))
        self.assertGreaterEqual(occupied, 1)
        open_wo = next(k["value"] for k in board["kpis"] if "Açıq WO" in str(k["label"]))
        self.assertGreaterEqual(open_wo, 0)

    def test_helpdesk_board_shape(self):
        board = build_helpdesk_dashboard(self.fm)
        self.assertIn("kpis", board)
        self.assertIn("pending", board)
        self.assertIn("quick_actions", board)
        hr = build_hr_dashboard(self.fm)
        self.assertIn("kpis", hr)
