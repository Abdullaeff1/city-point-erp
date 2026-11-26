"""Supply portal: spaces + resident companies are read-only (no master-data mutate)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.property.models import Building, Floor, Occupancy, Space
from apps.rbac.services import (
    SUPPLY_MASTER_DATA_MUTATIONS_NOT_ON_ROLE,
    grant_user_permission,
    list_supply_master_data_user_exceptions,
    seed_rbac_catalog,
    user_has_permission,
)
from apps.residents.models import ResidentCompany
from apps.residents.permissions import user_can_manage_resident_profile

User = get_user_model()


class SupplyReadonlySpacesResidentsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.staff = User.objects.create_user(
            username="ro-sd",
            email="ro-sd@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.head = User.objects.create_user(
            username="ro-head",
            email="ro-head@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(cls.head, "supply.head")
        cls.admin = User.objects.create_user(
            username="ro-admin",
            email="ro-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.company = ResidentCompany.objects.create(
            name="RO Co",
            slug="ro-co",
            contact_person_name="Nigar",
            contact_person_position="Ofis",
            contact_person_phone="+994501111111",
            contact_person_email="nigar@ro.co",
        )
        building = Building.objects.create(code="ROB", name="RO Bldg")
        floor = Floor.objects.create(building=building, code="2", name="2")
        cls.space = Space.objects.create(
            code="RO-201",
            name="Ofis 201",
            floor=floor,
            resident=cls.company,
            occupancy=Occupancy.ACTIVE_LEASE,
        )

    def test_matrix_denies_master_data_mutate_with_and_without_head(self):
        for user in (self.staff, self.head):
            self.assertTrue(user_has_permission(user, "space.view"))
            self.assertTrue(user_has_permission(user, "resident.view"))
            self.assertTrue(user_has_permission(user, "resident.directory.view"))
            self.assertFalse(user_has_permission(user, "space.edit"))
            self.assertFalse(user_has_permission(user, "resident.edit"))
            self.assertFalse(user_can_manage_resident_profile(user))
        self.assertTrue(user_has_permission(self.head, "procurement.edit"))
        self.assertFalse(user_has_permission(self.staff, "procurement.edit"))

    def test_supply_can_open_lists_and_details_ro(self):
        for user in (self.staff, self.head):
            c = Client()
            c.force_login(user)
            spaces = c.get(reverse("erp:spaces"))
            self.assertEqual(spaces.status_code, 200)
            self.assertContains(spaces, "RO-201")
            self.assertNotContains(spaces, reverse("erp:space_create"))
            detail = c.get(reverse("erp:space_detail", kwargs={"code": self.space.code}))
            self.assertEqual(detail.status_code, 200)
            self.assertNotContains(detail, reverse("erp:space_edit", args=[self.space.code]))
            self.assertNotContains(detail, reverse("erp:space_delete", args=[self.space.code]))
            directory = c.get(reverse("erp:resident_directory"))
            self.assertEqual(directory.status_code, 200)
            self.assertContains(directory, "RO Co")
            card = c.get(
                reverse("erp:resident_directory_detail", kwargs={"slug": self.company.slug})
            )
            self.assertEqual(card.status_code, 200)
            # Full CRUD residents list redirects to RO directory
            listed = c.get(reverse("erp:residents"))
            self.assertEqual(listed.status_code, 302)
            self.assertEqual(listed.url, reverse("erp:resident_directory"))

    def test_supply_direct_writes_denied_records_unchanged(self):
        original_name = self.space.name
        original_company = self.company.name
        for user in (self.staff, self.head):
            c = Client()
            c.force_login(user)
            create = c.get(reverse("erp:space_create"))
            self.assertIn(create.status_code, (302, 403))
            edit = c.post(
                reverse("erp:space_edit", kwargs={"code": self.space.code}),
                {
                    "code": self.space.code,
                    "name": "Hacked",
                    "floor": self.space.floor_id,
                    "area_m2": "10",
                    "occupancy": Occupancy.VACANT,
                    "commercial_status": "vacant",
                    "operational_status": "available",
                },
            )
            self.assertIn(edit.status_code, (302, 403))
            self.space.refresh_from_db()
            self.assertEqual(self.space.name, original_name)
            res_create = c.get(reverse("erp:resident_create"))
            self.assertIn(res_create.status_code, (302, 403))
            archive = c.post(
                reverse("erp:resident_archive", kwargs={"slug": self.company.slug})
            )
            self.assertIn(archive.status_code, (302, 403))
            self.company.refresh_from_db()
            self.assertEqual(self.company.name, original_company)
            self.assertFalse(self.company.is_archived)

    def test_admin_still_edits_space_and_resident(self):
        c = Client()
        c.force_login(self.admin)
        self.assertTrue(user_has_permission(self.admin, "space.edit"))
        self.assertTrue(user_can_manage_resident_profile(self.admin))
        spaces = c.get(reverse("erp:spaces"))
        self.assertEqual(spaces.status_code, 200)
        self.assertContains(spaces, reverse("erp:space_create"))
        detail = c.get(reverse("erp:space_detail", kwargs={"code": self.space.code}))
        self.assertContains(detail, reverse("erp:space_edit", args=[self.space.code]))
        residents = c.get(reverse("erp:residents"))
        self.assertEqual(residents.status_code, 200)
        self.assertContains(residents, reverse("erp:resident_create"))

    def test_explicit_userpermission_exception_listed_not_revoked(self):
        grant_user_permission(self.staff, "space.edit")
        self.assertTrue(user_has_permission(self.staff, "space.edit"))
        rows = list_supply_master_data_user_exceptions()
        self.assertTrue(
            any(
                row[0] == self.staff.pk and row[3] == "space.edit"
                for row in rows
            )
        )
        for code in SUPPLY_MASTER_DATA_MUTATIONS_NOT_ON_ROLE:
            self.assertIn(code, {"space.edit", "resident.edit"})
