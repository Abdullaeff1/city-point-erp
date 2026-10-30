from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.property.models import Building, Floor, Occupancy, Space
from apps.residents.models import ResidentCompany

User = get_user_model()


class SpaceCrudTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="adm-space",
            email="adm-space@test.az",
            password="Pass12345!",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.fm = User.objects.create_user(
            username="fm-space",
            email="fm-space@test.az",
            password="Pass12345!",
            role=Role.PROPERTY_FM,
            is_staff=True,
        )
        self.reception = User.objects.create_user(
            username="rec-space",
            email="rec-space@test.az",
            password="Pass12345!",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.building = Building.objects.create(code="CP-SC", name="City Point SC")
        self.floor = Floor.objects.create(building=self.building, code="F08", name="8-ci mərtəbə")
        self.company = ResidentCompany.objects.create(name="CRUD Co", slug="crud-co", portal_active=True)
        self.client = Client()

    def test_list_has_create_controls(self):
        self.client.force_login(self.fm)
        resp = self.client.get(reverse("erp:spaces"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("erp:space_create"))
        self.assertContains(resp, "Mərtəbə əlavə et")

    def test_create_floor_and_space(self):
        self.client.force_login(self.admin)
        floor_resp = self.client.post(
            reverse("erp:floor_create"),
            {"building": self.building.pk, "code": "f09", "name": "9-cu mərtəbə"},
        )
        self.assertEqual(floor_resp.status_code, 302)
        floor = Floor.objects.get(building=self.building, code="F09")
        self.assertEqual(floor.name, "9-cu mərtəbə")

        create_resp = self.client.post(
            reverse("erp:space_create"),
            {
                "code": "CP-L900",
                "name": "Test ofis",
                "floor": floor.pk,
                "resident": "",
                "area_m2": "120.5",
                "occupancy": Occupancy.VACANT,
                "commercial_status": "vacant",
                "operational_status": "available",
                "access_zone": "",
                "cost_center": "",
                "fit_out_status": "",
            },
        )
        self.assertEqual(create_resp.status_code, 302)
        space = Space.objects.get(code="CP-L900")
        self.assertEqual(space.floor_id, floor.pk)
        self.assertEqual(str(space.area_m2), "120.5")
        self.assertIsNone(space.resident_id)

    def test_update_and_delete_space(self):
        space = Space.objects.create(
            code="CP-L901",
            name="Old",
            floor=self.floor,
            area_m2="50",
            occupancy=Occupancy.VACANT,
        )
        self.client.force_login(self.fm)
        edit = self.client.post(
            reverse("erp:space_edit", args=[space.code]),
            {
                "code": "CP-L901",
                "name": "Yeni ad",
                "floor": self.floor.pk,
                "resident": self.company.pk,
                "area_m2": "75",
                "occupancy": Occupancy.VACANT,
                "commercial_status": "vacant",
                "operational_status": "available",
                "access_zone": "A",
                "cost_center": "CC1",
                "fit_out_status": "",
            },
        )
        self.assertEqual(edit.status_code, 302)
        space.refresh_from_db()
        self.assertEqual(space.name, "Yeni ad")
        self.assertEqual(space.resident_id, self.company.pk)
        self.assertEqual(space.occupancy, Occupancy.ACTIVE_LEASE)

        detail = self.client.get(reverse("erp:space_detail", args=[space.code]))
        self.assertContains(detail, reverse("erp:space_edit", args=[space.code]))
        self.assertContains(detail, reverse("erp:space_delete", args=[space.code]))

        delete = self.client.post(reverse("erp:space_delete", args=[space.code]))
        self.assertEqual(delete.status_code, 302)
        self.assertFalse(Space.objects.filter(code="CP-L901").exists())

    def test_reception_denied(self):
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse("erp:spaces")).status_code, 403)
        self.assertEqual(self.client.get(reverse("erp:space_create")).status_code, 403)
