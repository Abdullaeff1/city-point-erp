"""Supply portal browser-equivalent login landing (POST form, not force_login)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.rbac.services import grant_user_permission, seed_rbac_catalog

User = get_user_model()


class SupplyLoginLandingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.head = User.objects.create_user(
            username="login-head",
            email="login-head@test.az",
            password="HeadPass!2026",
            role=Role.SERVICE_DESK,
            is_staff=True,
            is_active=True,
        )
        grant_user_permission(cls.head, "supply.head")
        cls.staff = User.objects.create_user(
            username="login-staff",
            email="login-staff@test.az",
            password="StaffPass!2026",
            role=Role.SERVICE_DESK,
            is_staff=True,
            is_active=True,
        )

    def test_head_post_login_lands_on_supply_dashboard(self):
        c = Client()
        login_page = c.get(reverse("login"))
        self.assertEqual(login_page.status_code, 200)
        self.assertContains(login_page, 'id="cp-login-form"')
        self.assertContains(login_page, 'id="cp-login-lang"')
        resp = c.post(
            reverse("login"),
            {"email": "login-head@test.az", "password": "HeadPass!2026"},
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("post_login"))
        go = c.get(reverse("post_login"), follow=False)
        self.assertEqual(go.status_code, 302)
        self.assertIn("/erp/dashboards/supply/", go["Location"])
        final = c.get(reverse("erp:supply_dashboard"))
        self.assertEqual(final.status_code, 200)
        self.assertContains(final, "Təchizat")
        helpdesk = c.get(reverse("erp:helpdesk_dashboard"), follow=False)
        self.assertIn(helpdesk.status_code, (301, 302))
        self.assertIn("/erp/dashboards/supply/", helpdesk["Location"])
        pending = c.get(reverse("erp:procurement_pending_approvals"))
        self.assertEqual(pending.status_code, 200)
        self.assertFalse(pending.context["can_decide"])
        ready = c.get(reverse("erp:procurement_ready_to_issue"))
        self.assertEqual(ready.status_code, 200)

    def test_ordinary_staff_post_login_lands_on_supply(self):
        c = Client()
        resp = c.post(
            reverse("login"),
            {"email": "login-staff@test.az", "password": "StaffPass!2026"},
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)
        go = c.get(reverse("post_login"), follow=False)
        self.assertEqual(go.status_code, 302)
        self.assertIn("/erp/dashboards/supply/", go["Location"])
        dash = c.get(reverse("erp:supply_dashboard"))
        self.assertEqual(dash.status_code, 200)
        c2 = Client()
        bad = c2.post(
            reverse("login"),
            {"email": "login-staff@test.az", "password": "wrong"},
        )
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, "yanlış")
        self.assertFalse(bad.wsgi_request.user.is_authenticated)
