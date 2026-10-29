from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.property.models import Building, Floor, Space
from apps.residents.models import ResidentCompany

User = get_user_model()


class PortalSpaceDetailTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="ASBC Portal", slug="asbc-portal", portal_active=True
        )
        other = ResidentCompany.objects.create(
            name="Other Co", slug="other-co", portal_active=True
        )
        building = Building.objects.create(code="CP", name="City Point")
        floor = Floor.objects.create(building=building, code="F8", name="8-ci mərtəbə")
        self.space = Space.objects.create(
            code="CP-F08-OFF-249",
            name="249",
            floor=floor,
            resident=self.company,
            area_m2="249",
        )
        self.other_space = Space.objects.create(
            code="CP-F08-OFF-250",
            name="250",
            floor=floor,
            resident=other,
            area_m2="120",
        )
        self.user = User.objects.create_user(
            username="portal-space",
            email="office@asbc-portal.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_spaces_list_links_to_detail(self):
        resp = self.client.get(reverse("portal:spaces"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("portal:space_detail", args=[self.space.code]))
        self.assertContains(resp, "CP/F8/249")

    def test_own_space_detail_ok(self):
        resp = self.client.get(reverse("portal:space_detail", args=[self.space.code]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ümumi")
        self.assertContains(resp, "Müraciətlər")
        self.assertContains(resp, self.space.area_code)

    def test_other_company_space_forbidden(self):
        resp = self.client.get(reverse("portal:space_detail", args=[self.other_space.code]))
        self.assertEqual(resp.status_code, 404)
