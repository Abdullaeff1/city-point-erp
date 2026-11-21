"""Logout → shared login; login → role home; no dead 403 card."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.impersonation import SESSION_IMPERSONATOR_ID
from apps.accounts.models import Role
from apps.accounts.routing import home_url_name_for

User = get_user_model()


class LogoutAlwaysLoginTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(
            username="lo_sales",
            email="lo_sales@test.az",
            password="Pass12345!",
            role=Role.SALES,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="lo_admin",
            email="lo_admin@test.az",
            password="Pass12345!",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )

    def test_post_logout_lands_on_login(self):
        c = Client()
        c.force_login(self.sales)
        resp = c.post(reverse("logout"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("login"))
        follow = c.get(resp.url)
        self.assertEqual(follow.status_code, 200)
        self.assertContains(follow, "Xoş gəlmisiniz")
        self.assertFalse(follow.wsgi_request.user.is_authenticated)

    def test_get_logout_lands_on_login(self):
        c = Client()
        c.force_login(self.admin)
        resp = c.get(reverse("logout"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("login"))

    def test_logout_clears_impersonation(self):
        c = Client()
        c.force_login(self.admin)
        c.post(reverse("accounts:switch_role", args=[Role.SALES]))
        self.assertTrue(c.session.get(SESSION_IMPERSONATOR_ID))
        c.post(reverse("logout"))
        self.assertIsNone(c.session.get(SESSION_IMPERSONATOR_ID))
        self.assertFalse(c.session.get("_auth_user_id"))


class LoginRoleHomeTests(TestCase):
    def setUp(self):
        self.password = "Pass12345!"
        self.sales = User.objects.create_user(
            username="li_sales",
            email="li_sales@test.az",
            password=self.password,
            role=Role.SALES,
            is_staff=True,
        )
        self.reception = User.objects.create_user(
            username="li_rec",
            email="li_rec@test.az",
            password=self.password,
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.accountant = User.objects.create_user(
            username="li_acc",
            email="li_acc@test.az",
            password=self.password,
            role=Role.ACCOUNTANT,
            is_staff=True,
        )

    def _login(self, email):
        c = Client()
        resp = c.post(
            reverse("login"),
            {"email": email, "password": self.password},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("post_login"))
        home = c.get(resp.url)
        self.assertEqual(home.status_code, 302)
        return c, home["Location"]

    def test_sales_login_ignores_next_and_lands_on_dashboard(self):
        c = Client()
        resp = c.post(
            reverse("login") + "?next=/erp/audit/",
            {"email": self.sales.email, "password": self.password},
        )
        self.assertEqual(resp.url, reverse("post_login"))
        land = c.get(resp.url)
        self.assertEqual(land["Location"], reverse("erp:dashboard"))
        page = c.get(land["Location"])
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.context["is_sales_dashboard"])
        self.assertNotContains(page, "giriş icazəniz yoxdur")

    def test_reception_login_lands_on_reception(self):
        _, loc = self._login(self.reception.email)
        self.assertEqual(loc, reverse("erp:reception"))

    def test_accountant_login_lands_on_finance(self):
        _, loc = self._login(self.accountant.email)
        self.assertEqual(loc, reverse("finance:home"))

    def test_home_url_names(self):
        self.assertEqual(home_url_name_for(self.sales), "erp:dashboard")
        self.assertEqual(home_url_name_for(self.reception), "erp:reception")
        self.assertEqual(home_url_name_for(self.accountant), "finance:home")


@override_settings(DEBUG=True)
class SoftPermissionDeniedTests(TestCase):
    def setUp(self):
        self.sales = User.objects.create_user(
            username="pd_sales",
            email="pd_sales@test.az",
            password="Pass12345!",
            role=Role.SALES,
            is_staff=True,
        )

    def test_forbidden_page_redirects_home_not_403_body(self):
        from django.contrib.messages import get_messages

        c = Client()
        c.force_login(self.sales)
        resp = c.get(reverse("erp:audit"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))
        # Soft deny flash must persist across redirect (MessageMiddleware).
        page = c.get(resp.url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "giriş icazəniz yoxdur")
        msgs = [str(m) for m in get_messages(page.wsgi_request)]
        self.assertTrue(
            any("icazə" in m.lower() for m in msgs),
            f"expected soft-deny flash on home after redirect, got {msgs!r}",
        )
