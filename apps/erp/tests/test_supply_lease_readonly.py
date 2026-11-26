"""Supply must not mutate leases via role; authorized Finance/Sales keep edit."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.leases.models import Lease, LeaseStatus
from apps.parties.models import Party
from apps.rbac.services import (
    grant_user_permission,
    list_supply_lease_user_exceptions,
    seed_rbac_catalog,
    user_has_permission,
)
from apps.property.models import Building, Floor, Space

User = get_user_model()


class SupplyLeaseReadonlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.desk = User.objects.create_user(
            username="lease-sd",
            email="lease-sd@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.head = User.objects.create_user(
            username="lease-head",
            email="lease-head@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(cls.head, "supply.head")
        cls.sales = User.objects.create_user(
            username="lease-sales",
            email="lease-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        party = Party.objects.create(legal_name="Lease Co")
        building = Building.objects.create(code="LLB", name="Lease Bldg")
        floor = Floor.objects.create(building=building, code="1", name="1")
        space = Space.objects.create(code="LL-101", name="Office", floor=floor)
        cls.lease = Lease.objects.create(
            party=party,
            space=space,
            status=LeaseStatus.DRAFT,
            code="LL-TEST-1",
        )

    def test_supply_role_has_no_lease_perms(self):
        for user in (self.desk, self.head):
            self.assertFalse(user_has_permission(user, "lease.view"))
            self.assertFalse(user_has_permission(user, "lease.edit"))

    def test_supply_direct_lease_write_unchanged(self):
        original = self.lease.status
        for user in (self.desk, self.head):
            c = Client()
            c.force_login(user)
            resp = c.post(
                reverse("erp:lease_detail", kwargs={"code": self.lease.code}),
                {"action": "activate"},
            )
            self.assertIn(resp.status_code, (302, 403))
            self.lease.refresh_from_db()
            self.assertEqual(self.lease.status, original)

    def test_sales_can_edit_lease(self):
        self.assertTrue(user_has_permission(self.sales, "lease.edit"))
        c = Client()
        c.force_login(self.sales)
        detail = c.get(reverse("erp:lease_detail", kwargs={"code": self.lease.code}))
        self.assertEqual(detail.status_code, 200)

    def test_explicit_lease_exception_listed(self):
        grant_user_permission(self.desk, "lease.edit")
        self.assertTrue(user_has_permission(self.desk, "lease.edit"))
        rows = list_supply_lease_user_exceptions()
        self.assertTrue(any(r[0] == self.desk.pk and r[3] == "lease.edit" for r in rows))
