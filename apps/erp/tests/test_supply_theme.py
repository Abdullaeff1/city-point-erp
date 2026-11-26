"""Supply portal theme shell — scoped palette class on ERP chrome."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.rbac.services import grant_user_permission, seed_rbac_catalog

User = get_user_model()


class SupplyThemeShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.head = User.objects.create_user(
            username="theme-head",
            email="theme-head@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(cls.head, "supply.head")
        cls.staff = User.objects.create_user(
            username="theme-staff",
            email="theme-staff@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.manager = User.objects.create_user(
            username="theme-mgr",
            email="theme-mgr@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )

    def test_supply_head_shell_uses_supply_theme(self):
        c = Client()
        c.force_login(self.head)
        resp = c.get(reverse("erp:supply_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_supply_portal"])
        self.assertContains(resp, "cp-theme-supply")
        self.assertContains(resp, "css/cp-supply.css")
        self.assertNotContains(resp, "cp-theme-mgmt")
        self.assertNotContains(resp, "cp-theme-crm")

    def test_ordinary_service_desk_shell_uses_supply_theme(self):
        c = Client()
        c.force_login(self.staff)
        for name in (
            "erp:supply_dashboard",
            "erp:tickets",
            "erp:work_orders",
            "erp:warehouse",
            "erp:procurement",
        ):
            resp = c.get(reverse(name))
            self.assertEqual(resp.status_code, 200, msg=name)
            self.assertContains(resp, "cp-theme-supply", msg_prefix=name)

    def test_management_shared_route_keeps_mgmt_theme(self):
        c = Client()
        c.force_login(self.manager)
        resp = c.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cp-theme-mgmt")
        self.assertNotContains(resp, "cp-theme-supply")
        # Shared operational route still Management-scoped.
        tickets = c.get(reverse("erp:tickets"))
        self.assertEqual(tickets.status_code, 200)
        self.assertContains(tickets, "cp-theme-mgmt")
        self.assertNotContains(tickets, "cp-theme-supply")
