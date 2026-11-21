"""Rəhbərlik ERP modul hub — theme, modul kartları, şöbə portalı deep-link yox."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role

User = get_user_model()


class ManagementHubTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="mgr_hub",
            email="mgr_hub@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="admin_hub",
            email="admin_hub@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="sales_hub",
            email="sales_hub@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        self.client = Client()

    def test_management_dashboard_hub(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_management_hub"])
        self.assertFalse(resp.context.get("is_sales_dashboard"))
        self.assertContains(resp, "cp-theme-crm")
        self.assertContains(resp, "mgmt-module-card")
        self.assertEqual(len(resp.context["hub_modules"]), 11)
        keys = [m["key"] for m in resp.context["hub_modules"]]
        self.assertIn("residents", keys)
        self.assertEqual(
            next(m["url"] for m in resp.context["hub_modules"] if m["key"] == "residents"),
            reverse("erp:residents"),
        )
        self.assertContains(resp, "ERP Dashboard")
        self.assertContains(resp, reverse("erp:residents"))
        # Must not deep-link dedicated portals from hub body
        body = resp.content.decode("utf-8")
        for m in resp.context["hub_modules"]:
            self.assertTrue(m["url"].startswith("/erp/") or "/crm/" in m["url"])
            self.assertNotIn("/security/", m["url"])
            self.assertNotIn("/finance/", m["url"])
        self.assertNotIn('href="/security/"', body)
        self.assertNotIn('href="/finance/"', body)

    def test_admin_keeps_ops_not_hub(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("erp:dashboard") + "?ops=1")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context.get("is_management_hub"))
        self.assertNotContains(resp, "mgmt-module-card")
        self.assertNotContains(resp, "cp-theme-crm")

    def test_sales_unchanged(self):
        self.client.force_login(self.sales)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_sales_dashboard"])
        self.assertFalse(resp.context.get("is_management_hub"))
        self.assertContains(resp, "cp-theme-crm")

    def test_management_module_urls_ok(self):
        from apps.residents.models import ResidentCompany

        ResidentCompany.objects.create(
            name="City Point", slug="city-point", status="active", is_internal=True
        )
        tenant = ResidentCompany.objects.create(
            name="Acme MMC", slug="acme-mmc", status="active", is_internal=False
        )
        self.client.force_login(self.manager)
        paths = [
            reverse("erp:dashboard"),
            reverse("erp:residents"),
            reverse("erp:resident_detail", kwargs={"slug": tenant.slug}),
            reverse("erp:tickets"),
            reverse("erp:documents"),
            reverse("erp:spaces"),
            reverse("erp:warehouse"),
            reverse("erp:procurement"),
            reverse("erp:people_inside"),
            reverse("erp:reports"),
            reverse("erp:crm_leads"),
            reverse("erp:internal_staff_access"),
            reverse("erp:ar_aging"),
            reverse("erp:announcements"),
        ]
        for path in paths:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, msg=path)
            self.assertContains(resp, "cp-theme-crm", msg_prefix=path)

    def test_management_residents_list_links_to_detail(self):
        from apps.residents.models import ResidentCompany

        company = ResidentCompany.objects.create(
            name="Orbit LLC", slug="orbit-llc", status="active", is_internal=False
        )
        self.client.force_login(self.manager)
        list_resp = self.client.get(reverse("erp:residents"))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, reverse("erp:resident_detail", kwargs={"slug": company.slug}))
        self.assertContains(list_resp, "Orbit LLC")

        detail = self.client.get(reverse("erp:resident_detail", kwargs={"slug": company.slug}))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Orbit LLC")
        self.assertTrue(detail.context.get("can_view_legal"))
        self.assertContains(detail, reverse("erp:residents"))

    def test_management_blocked_from_reception_and_space_create(self):
        self.client.force_login(self.manager)
        # Reception is department portal — redirect home
        resp = self.client.get(reverse("erp:reception"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))

    def test_management_cannot_mutate_tickets(self):
        from apps.tickets.access import can_mutate_ticket

        class _T:
            pass

        self.assertFalse(can_mutate_ticket(self.manager, _T()))
