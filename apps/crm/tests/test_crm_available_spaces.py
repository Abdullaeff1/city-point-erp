"""CRM əlçatan sahələr paneli — sales ACL, siyahı, detail."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.crm.dashboard import build_sales_dashboard
from apps.leases.models import Lease, LeaseStatus
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


class CrmAvailableSpacesTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(
            username="sp_sales",
            email="sp_sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        self.reception = User.objects.create_user(
            username="sp_rec",
            email="sp_rec@test.az",
            password="x",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="sp_admin",
            email="sp_admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
        )
        b = Building.objects.create(code="SPS", name="SP Sales")
        self.floor = Floor.objects.create(building=b, code="F2", name="2")
        self.free = Space.objects.create(
            code="SP-FREE-1",
            floor=self.floor,
            area_m2=Decimal("120"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.VACANT,
            fit_out_status="Təmirli",
            renovation_needed=False,
            has_internal_kitchen=True,
            parking_included=True,
            parking_slots=2,
            sales_notes="Pəncərə cənub",
            base_rent_rate=Decimal("25.00"),
        )
        self.held = Space.objects.create(
            code="SP-HELD-1",
            floor=self.floor,
            area_m2=Decimal("90"),
            commercial_status=CommercialStatus.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
            occupancy=Occupancy.ACTIVE_LEASE,
        )
        self.party = Party.objects.create(
            legal_name="Köhnə MMC",
            party_type=PartyType.ORGANIZATION,
            status=PartyStatus.ACTIVE,
        )
        Lease.objects.create(
            code="LS-OLD-1",
            party=self.party,
            space=self.free,
            status=LeaseStatus.TERMINATED,
            start_date="2024-01-01",
            end_date="2025-01-01",
        )

    def test_sales_list_shows_available_not_held(self):
        c = Client()
        c.force_login(self.sales)
        resp = c.get(reverse("erp:crm_available_spaces"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Əlçatan sahələr")
        self.assertContains(resp, self.free.code)
        self.assertNotContains(resp, self.held.code)
        self.assertContains(resp, "Var")  # kitchen / parking

    def test_sales_detail_shows_amenities_and_history(self):
        c = Client()
        c.force_login(self.sales)
        resp = c.get(reverse("erp:crm_space_detail", kwargs={"code": self.free.code}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Daxili mətbəx")
        self.assertContains(resp, "Pəncərə cənub")
        self.assertContains(resp, "Köhnə MMC")
        self.assertContains(resp, "Təmirli")
        self.assertTrue(resp.context["available_now"])

    def test_occupied_space_detail_banner(self):
        c = Client()
        c.force_login(self.sales)
        resp = c.get(reverse("erp:crm_space_detail", kwargs={"code": self.held.code}))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["available_now"])
        self.assertContains(resp, "əlçatan siyahıda deyil")

    def test_reception_denied(self):
        c = Client()
        c.force_login(self.reception)
        resp = c.get(reverse("erp:crm_available_spaces"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:reception"))

    def test_admin_denied_crm_spaces(self):
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse("erp:crm_available_spaces"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))

    def test_fm_spaces_still_blocked_for_sales(self):
        c = Client()
        c.force_login(self.sales)
        resp = c.get(reverse("erp:spaces"))
        self.assertEqual(resp.status_code, 302)

    def test_dashboard_kpi_links_to_crm_spaces(self):
        data = build_sales_dashboard(self.sales, {})
        self.assertIn("/erp/crm/spaces/", data["kpi"]["available_spaces"]["url"])
        self.assertNotIn("available_space_rows", data)
