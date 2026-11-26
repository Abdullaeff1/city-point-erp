"""Shared City Point palette — theme classes and CSS load across shells."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.rbac.services import grant_user_permission, seed_rbac_catalog

User = get_user_model()


class SharedPaletteShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.desk = User.objects.create_user(
            username="pal-desk",
            email="pal-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(cls.desk, "supply.head")
        cls.manager = User.objects.create_user(
            username="pal-mgr",
            email="pal-mgr@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        cls.sales = User.objects.create_user(
            username="pal-sales",
            email="pal-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        cls.accountant = User.objects.create_user(
            username="pal-acc",
            email="pal-acc@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        cls.security = User.objects.create_user(
            username="pal-sec",
            email="pal-sec@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
        )
        cls.reception = User.objects.create_user(
            username="pal-rec",
            email="pal-rec@test.az",
            password="x",
            role=Role.RECEPTION,
            is_staff=True,
        )

    def test_shared_stylesheet_on_login(self):
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "css/cp-theme.css")
        self.assertContains(resp, "css/cp-supply.css")

    def test_management_keeps_layout_class_with_shared_palette(self):
        c = Client()
        c.force_login(self.manager)
        resp = c.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cp-theme-mgmt")
        self.assertContains(resp, "css/cp-theme.css")
        # Layout chrome preserved
        self.assertContains(resp, "cp-mgmt-header")

    def test_sales_crm_theme_class(self):
        c = Client()
        c.force_login(self.sales)
        resp = c.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cp-theme-crm")
        self.assertNotContains(resp, "cp-theme-mgmt")

    def test_supply_theme_class(self):
        c = Client()
        c.force_login(self.desk)
        resp = c.get(reverse("erp:supply_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cp-theme-supply")

    def test_finance_and_security_load_shared_stack(self):
        c = Client()
        c.force_login(self.accountant)
        fin = c.get(reverse("finance:home"))
        self.assertEqual(fin.status_code, 200)
        self.assertContains(fin, "css/cp-theme.css")
        self.assertNotContains(fin, "cp-theme-mgmt")
        self.assertNotContains(fin, "cp-theme-crm")

        c2 = Client()
        c2.force_login(self.security)
        sec = c2.get(reverse("security:home"))
        self.assertEqual(sec.status_code, 200)
        self.assertContains(sec, "css/cp-theme.css")

    def test_reception_uses_shared_erp_shell(self):
        c = Client()
        c.force_login(self.reception)
        resp = c.get(reverse("erp:reception"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "cp-shell")
        self.assertContains(resp, "css/cp-theme.css")
