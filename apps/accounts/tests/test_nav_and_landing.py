"""Phase 3 — permission-aware nav flags and landing resolution."""

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.accounts.context_processors import role_context
from apps.accounts.models import Role
from apps.accounts.nav import build_nav_flags, list_workspaces, resolve_landing_url_name
from apps.accounts.routing import home_url_name_for
from apps.rbac.services import seed_rbac_catalog

User = get_user_model()


class LandingResolutionTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()

    def _user(self, username, role, **kwargs):
        return User.objects.create_user(
            username=username,
            email=f"{username}@test.az",
            password="x",
            role=role,
            is_staff=True,
            **kwargs,
        )

    def test_role_preferred_landings(self):
        self.assertEqual(resolve_landing_url_name(self._user("m", Role.MANAGEMENT)), "erp:dashboard")
        self.assertEqual(resolve_landing_url_name(self._user("r", Role.RECEPTION)), "erp:reception")
        self.assertEqual(resolve_landing_url_name(self._user("s", Role.SECURITY)), "security:home")
        self.assertEqual(resolve_landing_url_name(self._user("fm", Role.PROPERTY_FM)), "erp:facility_dashboard")
        self.assertEqual(resolve_landing_url_name(self._user("sa", Role.SALES)), "erp:dashboard")
        self.assertEqual(resolve_landing_url_name(self._user("a", Role.ACCOUNTANT)), "finance:home")
        self.assertEqual(resolve_landing_url_name(self._user("sd", Role.SERVICE_DESK)), "erp:helpdesk_dashboard")
        self.assertEqual(
            resolve_landing_url_name(self._user("ad", Role.ADMIN, is_superuser=True)),
            "erp:it_dashboard",
        )

    def test_home_url_name_for_delegates(self):
        sales = self._user("hs", Role.SALES)
        self.assertEqual(home_url_name_for(sales), resolve_landing_url_name(sales))

    def test_multi_workspace_switcher_for_admin(self):
        admin = self._user("aw", Role.ADMIN, is_superuser=True)
        ws = list_workspaces(admin)
        self.assertGreaterEqual(len(ws), 2)
        flags = build_nav_flags(admin)
        self.assertTrue(flags["nav_show_workspace_switcher"])
        self.assertFalse(flags["nav_crm"])  # A.10 Admin out of CRM nav


class NavFlagsTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.factory = RequestFactory()

    def test_sales_has_crm_not_audit(self):
        sales = User.objects.create_user(
            username="ns", email="ns@test.az", password="x", role=Role.SALES, is_staff=True
        )
        flags = build_nav_flags(sales)
        self.assertTrue(flags["nav_crm"])
        self.assertFalse(flags["nav_audit"])
        self.assertFalse(flags["nav_reception"])

    def test_reception_no_crm(self):
        rec = User.objects.create_user(
            username="nr", email="nr@test.az", password="x", role=Role.RECEPTION, is_staff=True
        )
        flags = build_nav_flags(rec)
        self.assertTrue(flags["nav_reception"])
        self.assertFalse(flags["nav_crm"])
        self.assertTrue(flags.get("nav_parties") or flags["nav_residents"])

    def test_fm_has_work_orders_not_reception_desk(self):
        fm = User.objects.create_user(
            username="nfm", email="nfm@test.az", password="x", role=Role.PROPERTY_FM, is_staff=True
        )
        flags = build_nav_flags(fm)
        self.assertTrue(flags["nav_work_orders"])
        self.assertFalse(flags["nav_reception"])

    def test_context_processor_exposes_nav(self):
        from django.contrib.sessions.middleware import SessionMiddleware

        sales = User.objects.create_user(
            username="nc", email="nc@test.az", password="x", role=Role.SALES, is_staff=True
        )
        req = self.factory.get("/")
        req.user = sales
        SessionMiddleware(lambda r: None).process_request(req)
        req.session.save()
        ctx = role_context(req)
        self.assertTrue(ctx["nav_crm"])
        self.assertIn("nav_workspaces", ctx)


@override_settings(DEBUG=True)
class UnauthorizedDashboardTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.sales = User.objects.create_user(
            username="ud_s", email="ud_s@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.client = Client()

    def test_sales_hr_dashboard_soft_denied(self):
        self.client.force_login(self.sales)
        resp = self.client.get(reverse("erp:hr_dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("icazə" in m.lower() for m in msgs))

    def test_sales_it_dashboard_denied(self):
        self.client.force_login(self.sales)
        resp = self.client.get(reverse("erp:it_dashboard"))
        self.assertEqual(resp.status_code, 302)
