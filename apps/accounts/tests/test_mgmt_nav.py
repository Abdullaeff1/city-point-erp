"""Rəhbərlik collapsible nav — icazə, marşrut, rol sərhədi."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.mgmt_nav import build_management_nav
from apps.accounts.models import Role
from apps.accounts.nav import build_nav_flags
from apps.rbac.services import seed_rbac_catalog

User = get_user_model()


class ManagementNavTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.manager = User.objects.create_user(
            username="mgr_nav",
            email="mgr_nav@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="sales_nav",
            email="sales_nav@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        self.client = Client()

    def test_build_management_nav_groups(self):
        groups = build_management_nav(self.manager, url_name="dashboard")
        keys = [g["key"] for g in groups]
        self.assertIn("dashboard", keys)
        self.assertIn("property", keys)
        self.assertIn("commercial", keys)
        self.assertIn("operations", keys)
        self.assertIn("supply", keys)
        self.assertIn("docs_comms", keys)
        self.assertIn("finance", keys)
        self.assertIn("reports", keys)
        labels = {g["label"] for g in groups}
        self.assertTrue(any("Əmlak" in str(x) for x in labels))
        self.assertTrue(any("Kommersiya" in str(x) or "kommersiya" in str(x).lower() for x in labels))

        urls = {i["url"] for g in groups for i in g.get("items") or []}
        dash = next(g for g in groups if g["key"] == "dashboard")
        self.assertEqual(dash.get("kind"), "link")
        self.assertEqual(dash["url"], reverse("erp:dashboard"))
        urls.add(dash["url"])
        self.assertIn(reverse("erp:leases"), urls)
        self.assertIn(f"{reverse('erp:payment_approvals')}?queue=ar", urls)
        self.assertIn(f"{reverse('erp:payment_approvals')}?queue=ap", urls)
        self.assertNotIn(reverse("erp:reception"), urls)
        joined = " ".join(urls)
        self.assertNotIn("/security/", joined)
        self.assertNotIn("/finance/", joined)

    def test_dashboard_direct_link_no_nested_overview(self):
        groups = build_management_nav(self.manager, url_name="dashboard")
        dash = next(g for g in groups if g["key"] == "dashboard")
        self.assertEqual(dash.get("kind"), "link")
        self.assertTrue(dash["is_active"])
        self.assertEqual(dash["items"], [])
        self.assertFalse(any("Ümumi baxış" in str(g.get("label", "")) for g in groups))
        self.assertFalse(
            any(
                "Ümumi baxış" in str(i.get("label", ""))
                for g in groups
                for i in (g.get("items") or [])
            )
        )
        # Only the active group may be open — finance must not stay forced-open on dashboard.
        finance_on_dash = next(g for g in groups if g["key"] == "finance")
        self.assertFalse(finance_on_dash["is_open"])
        self.assertFalse(finance_on_dash["is_active"])
        docs = next(g for g in groups if g["key"] == "docs_comms")
        self.assertEqual(docs["icon"], "file-text")
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertContains(resp, "cp-nav-direct")
        self.assertNotContains(resp, "Ümumi baxış")
        self.assertContains(resp, 'data-lucide="file-text"')
        # Child page expands its group and marks the leaf active
        groups2 = build_management_nav(
            self.manager, url_name="payment_approvals", query={"queue": "ap"}
        )
        finance = next(g for g in groups2 if g["key"] == "finance")
        self.assertTrue(finance["is_open"])
        self.assertTrue(finance["is_active"])
        ap = next(i for i in finance["items"] if "queue=ap" in i["url"])
        self.assertTrue(ap["is_active"])
        dash2 = next(g for g in groups2 if g["key"] == "dashboard")
        self.assertFalse(dash2["is_active"])

    def test_sales_gets_empty_mgmt_nav(self):
        self.assertEqual(build_management_nav(self.sales, url_name="dashboard"), [])

    def test_nav_leases_enabled_for_management(self):
        flags = build_nav_flags(self.manager)
        self.assertTrue(flags["nav_leases"])
        self.assertFalse(flags["nav_reception"])
        self.assertFalse(flags["nav_show_workspace_switcher"])

    def test_active_state_payment_queues(self):
        groups = build_management_nav(
            self.manager, url_name="payment_approvals", query={"queue": "ap"}
        )
        finance = next(g for g in groups if g["key"] == "finance")
        ar = next(i for i in finance["items"] if "queue=ar" in i["url"])
        ap = next(i for i in finance["items"] if "queue=ap" in i["url"])
        self.assertFalse(ar["is_active"])
        self.assertTrue(ap["is_active"])

    def test_management_sidebar_renders_and_routes(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context.get("mgmt_nav_groups"))
        self.assertContains(resp, "cp-theme-mgmt")
        self.assertContains(resp, 'data-mgmt-nav="finance"')
        self.assertContains(resp, "mgmt-account")
        self.assertNotContains(resp, "İş sahələri")

        for path in (
            reverse("erp:leases") + "?filter=expiring",
            reverse("erp:payment_approvals") + "?queue=ar",
            reverse("erp:payment_approvals") + "?queue=ap",
            reverse("erp:approvals") + "?workflow=crm.offer.send",
            reverse("erp:spaces") + "?status=vacant",
        ):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, msg=path)
            self.assertContains(r, "cp-theme-mgmt", msg_prefix=path)

    def test_management_reception_still_blocked(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("erp:reception"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))

    def test_management_cannot_open_finance_portal(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("finance:home"))
        self.assertIn(resp.status_code, (302, 403))
