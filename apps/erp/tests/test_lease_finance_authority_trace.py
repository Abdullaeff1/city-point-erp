"""Trace Sales / Accountant / Admin lease+finance routes without broadening grants."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.finance.access import can_mutate_finance
from apps.leases.models import Lease, LeaseStatus
from apps.parties.models import Party
from apps.property.models import Building, Floor, Space
from apps.rbac.services import seed_rbac_catalog, user_has_permission

User = get_user_model()


class LeaseFinanceAuthorityTraceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.sales = User.objects.create_user(
            username="lf-sales",
            email="lf-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        cls.accountant = User.objects.create_user(
            username="lf-acct",
            email="lf-acct@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        cls.admin = User.objects.create_user(
            username="lf-admin",
            email="lf-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.desk = User.objects.create_user(
            username="lf-desk",
            email="lf-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        party = Party.objects.create(legal_name="LF Party")
        building = Building.objects.create(code="LFB", name="LF Bldg")
        floor = Floor.objects.create(building=building, code="1", name="1")
        space = Space.objects.create(code="LF-101", name="Office", floor=floor)
        cls.lease = Lease.objects.create(
            party=party,
            space=space,
            status=LeaseStatus.DRAFT,
            code="LF-LEASE-1",
        )

    def test_permission_matrix_by_role(self):
        self.assertTrue(user_has_permission(self.sales, "lease.view"))
        self.assertTrue(user_has_permission(self.sales, "lease.edit"))
        self.assertTrue(user_has_permission(self.sales, "crm.edit"))
        self.assertTrue(user_has_permission(self.accountant, "lease.view"))
        self.assertFalse(user_has_permission(self.accountant, "lease.edit"))
        self.assertTrue(can_mutate_finance(self.accountant))
        self.assertFalse(can_mutate_finance(self.sales))
        self.assertFalse(user_has_permission(self.desk, "lease.view"))
        self.assertFalse(user_has_permission(self.desk, "lease.edit"))

    def test_erp_lease_mutations_require_lease_edit(self):
        """ERP lease detail POST: activate/terminate/charges/deposit gated by lease.edit."""
        for user, allowed in (
            (self.sales, True),
            (self.accountant, False),
            (self.desk, False),
        ):
            before = self.lease.status
            c = Client()
            c.force_login(user)
            for action in ("activate", "terminate", "generate_charges", "settle_deposit"):
                status_before = self.lease.status
                r = c.post(
                    reverse("erp:lease_detail", kwargs={"code": self.lease.code}),
                    {"action": action},
                )
                self.lease.refresh_from_db()
                if allowed:
                    self.assertNotEqual(r.status_code, 403, msg=action)
                else:
                    self.assertIn(r.status_code, (302, 403), msg=action)
                    self.assertEqual(self.lease.status, status_before)
            self.lease.status = before
            self.lease.save(update_fields=["status"])

    def test_finance_portal_charge_generation_route(self):
        """Accountant charge generation is Finance portal mutate — not lease.edit."""
        c = Client()
        c.force_login(self.accountant)
        # Finance dashboard / receivables entry points exist for accountant
        for name in ("finance:home", "finance:charges"):
            url = reverse(name)
            r = c.get(url)
            self.assertIn(r.status_code, (200, 302), msg=name)
        # Sales must not mutate finance
        self.assertFalse(can_mutate_finance(self.sales))

    def test_documented_gaps_are_explicit(self):
        """Record policy mismatches for the owner — do not 'fix' by granting lease.edit."""
        # Sales has ERP lease.edit (activate/terminate/charges/deposit) while documented
        # CRM ownership is offer/application preparation; lease draft creation is Accountant.
        self.assertTrue(user_has_permission(self.sales, "lease.edit"))
        # Accountant lacks ERP lease.edit so cannot use LeaseDetailView actions; Finance
        # portal owns charge generation via can_mutate_finance.
        self.assertFalse(user_has_permission(self.accountant, "lease.edit"))
        self.assertTrue(can_mutate_finance(self.accountant))
