"""Resident directory: search by display office label, floor, and internal code."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.property.models import Building, CommercialStatus, Floor, Occupancy, Space
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import ResidentCompany

User = get_user_model()


class DirectoryOfficeSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.desk = User.objects.create_user(
            username="dir-sd",
            email="dir-sd@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.company = ResidentCompany.objects.create(
            name="Directory Search Co",
            slug="dir-search-co",
            contact_person_name="Ayna",
            contact_person_phone="+994501234567",
        )
        other = ResidentCompany.objects.create(
            name="Other Tenant Co",
            slug="other-tenant-co",
        )
        building = Building.objects.create(code="DSC", name="Dir Bldg")
        floor8 = Floor.objects.create(building=building, code="F08", name="8")
        floor3 = Floor.objects.create(building=building, code="F03", name="3")
        cls.space_a = Space.objects.create(
            code="DIR-L049",
            name="Office A",
            floor=floor8,
            resident=cls.company,
            area_m2="249",
            occupancy=Occupancy.ACTIVE_LEASE,
            commercial_status=CommercialStatus.ACTIVE,
        )
        cls.space_b = Space.objects.create(
            code="DIR-L050",
            name="Office B",
            floor=floor8,
            resident=cls.company,
            area_m2="100",
            occupancy=Occupancy.ACTIVE_LEASE,
            commercial_status=CommercialStatus.ACTIVE,
        )
        Space.objects.create(
            code="DIR-OTHER",
            name="Other",
            floor=floor3,
            resident=other,
            area_m2="50",
            occupancy=Occupancy.ACTIVE_LEASE,
            commercial_status=CommercialStatus.ACTIVE,
        )
        cls.label = cls.space_a.short_label  # e.g. CP/F8/249

    def _search(self, q: str):
        c = Client()
        c.force_login(self.desk)
        return c.get(reverse("erp:resident_directory"), {"q": q})

    def test_name_search_returns_company_with_two_offices(self):
        r = self._search("Directory Search")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Directory Search Co")
        self.assertContains(r, self.space_a.short_label)
        self.assertContains(r, self.space_b.short_label)

    def test_copied_office_label_finds_company(self):
        r = self._search(self.label)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Directory Search Co")
        self.assertNotContains(r, "Other Tenant Co")

    def test_floor_code_finds_company(self):
        r = self._search("F08")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Directory Search Co")

    def test_internal_code_finds_company(self):
        r = self._search("DIR-L049")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Directory Search Co")

    def test_unknown_query_empty(self):
        r = self._search("zz-no-such-office-xyz")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Directory Search Co")
        self.assertNotContains(r, "Other Tenant Co")
