"""Phase 2 — role × permission matrix and soft-deny feedback."""

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role
from apps.crm.access import can_approve_offer, can_mutate_crm, can_view_crm
from apps.management.access import can_decide_approvals
from apps.rbac.services import (
    ROLE_MATRIX,
    seed_rbac_catalog,
    user_has_permission,
)
from apps.tickets.access import can_mutate_ticket, can_view_ticket
from apps.tickets.models import Ticket, TicketCategory
from apps.residents.models import ResidentCompany

User = get_user_model()


class PermissionCatalogTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()

    def test_sales_has_crm_not_audit(self):
        sales = User.objects.create_user(
            username="mx_sales", email="mx_sales@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.assertTrue(user_has_permission(sales, "crm.view"))
        self.assertTrue(user_has_permission(sales, "crm.edit"))
        self.assertFalse(user_has_permission(sales, "audit.view"))
        self.assertFalse(user_has_permission(sales, "finance.edit"))

    def test_management_ro_mutate_codes(self):
        mgmt = User.objects.create_user(
            username="mx_mgmt", email="mx_mgmt@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.assertTrue(user_has_permission(mgmt, "crm.view"))
        self.assertTrue(user_has_permission(mgmt, "crm.approve"))
        self.assertFalse(user_has_permission(mgmt, "crm.edit"))
        self.assertFalse(user_has_permission(mgmt, "ticket.edit"))
        self.assertFalse(user_has_permission(mgmt, "finance.edit"))
        self.assertTrue(user_has_permission(mgmt, "work_order.view"))
        self.assertFalse(user_has_permission(mgmt, "work_order.edit"))
        self.assertFalse(user_has_permission(mgmt, "work_order.create"))
        self.assertTrue(user_has_permission(mgmt, "approval.decide"))
        self.assertTrue(user_has_permission(mgmt, "hr.view"))
        self.assertFalse(user_has_permission(mgmt, "announcement.publish"))

    def test_accountant_finance(self):
        acct = User.objects.create_user(
            username="mx_acct", email="mx_acct@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.assertTrue(user_has_permission(acct, "finance.view"))
        self.assertTrue(user_has_permission(acct, "finance.edit"))
        self.assertTrue(can_view_crm(acct))
        self.assertFalse(can_mutate_crm(acct))

    def test_supply_mutations_not_on_service_desk_role(self):
        """Təchizat role alone cannot mutate warehouse/procurement (needs supply.head)."""
        fm = User.objects.create_user(
            username="mx_fm", email="mx_fm@test.az", password="x", role=Role.SERVICE_DESK, is_staff=True
        )
        mgmt = User.objects.create_user(
            username="mx_mgmt_pr", email="mx_mgmt_pr@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.assertFalse(user_has_permission(fm, "procurement.approve"))
        self.assertFalse(user_has_permission(fm, "procurement.edit"))
        self.assertFalse(user_has_permission(fm, "warehouse.edit"))
        self.assertTrue(user_has_permission(fm, "procurement.view"))
        self.assertFalse(user_has_permission(mgmt, "procurement.approve"))
        self.assertTrue(user_has_permission(mgmt, "approval.decide"))
        self.assertNotIn("procurement.approve", ROLE_MATRIX[Role.SERVICE_DESK])
        self.assertNotIn("procurement.edit", ROLE_MATRIX[Role.SERVICE_DESK])
        self.assertNotIn("warehouse.edit", ROLE_MATRIX[Role.SERVICE_DESK])
        self.assertNotIn("procurement.approve", ROLE_MATRIX[Role.MANAGEMENT])

    def test_crm_dual_gate(self):
        sales = User.objects.create_user(
            username="mx_s2", email="mx_s2@test.az", password="x", role=Role.SALES, is_staff=True
        )
        mgmt = User.objects.create_user(
            username="mx_m2", email="mx_m2@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.assertTrue(can_view_crm(sales))
        self.assertTrue(can_mutate_crm(sales))
        self.assertTrue(can_view_crm(mgmt))
        self.assertFalse(can_mutate_crm(mgmt))
        self.assertTrue(can_approve_offer(mgmt))
        self.assertFalse(can_approve_offer(sales))

    def test_ticket_management_cannot_mutate(self):
        company = ResidentCompany.objects.create(name="T Co", slug="t-co-mx", is_internal=False)
        category = TicketCategory.objects.create(name="Ümumi", slug="umumi-mx")
        ticket = Ticket.objects.create(code="TK-MX1", category=category, company=company)
        mgmt = User.objects.create_user(
            username="mx_m3", email="mx_m3@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.assertTrue(can_view_ticket(mgmt, ticket))
        self.assertFalse(can_mutate_ticket(mgmt, ticket))

    def test_matrix_covers_required_domains(self):
        needed = {
            "resident.view",
            "crm.view",
            "finance.view",
            "warehouse.view",
            "procurement.view",
            "hr.view",
            "audit.view",
            "approval.decide",
            "security.view",
            "ticket.view",
            "space.view",
            "document.view",
            "report.view",
            "user.admin",
        }
        admin_codes = set(ROLE_MATRIX[Role.ADMIN])
        self.assertTrue(needed.issubset(admin_codes))


@override_settings(DEBUG=True)
class SoftPermissionDeniedMessageTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.sales = User.objects.create_user(
            username="pd_sales2",
            email="pd_sales2@test.az",
            password="Pass12345!",
            role=Role.SALES,
            is_staff=True,
        )

    def test_audit_denied_redirects_with_message(self):
        c = Client()
        c.force_login(self.sales)
        resp = c.get(reverse("erp:audit"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))
        msgs = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("icazə" in str(m).lower() or "Audit" in str(m) for m in msgs))


@override_settings(DEBUG=True)
class PortalIsolationPermissionTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.sales = User.objects.create_user(
            username="iso_sales", email="iso_s@test.az", password="x", role=Role.SALES, is_staff=True
        )
        self.reception = User.objects.create_user(
            username="iso_recv", email="iso_r@test.az", password="x", role=Role.RECEPTION, is_staff=True
        )
        self.accountant = User.objects.create_user(
            username="iso_acct", email="iso_a@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.security = User.objects.create_user(
            username="iso_sec", email="iso_sec@test.az", password="x", role=Role.SECURITY, is_staff=True
        )
        self.client = Client()

    def test_sales_cannot_open_finance_portal(self):
        self.client.force_login(self.sales)
        resp = self.client.get(reverse("finance:home"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))

    def test_reception_cannot_open_security_portal(self):
        self.client.force_login(self.reception)
        resp = self.client.get(reverse("security:home"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:reception"))

    def test_accountant_finance_ok(self):
        self.client.force_login(self.accountant)
        resp = self.client.get(reverse("finance:home"))
        self.assertEqual(resp.status_code, 200)

    def test_security_home_ok(self):
        self.client.force_login(self.security)
        resp = self.client.get(reverse("security:home"))
        self.assertEqual(resp.status_code, 200)

    def test_sales_cannot_open_warehouse(self):
        self.client.force_login(self.sales)
        resp = self.client.get(reverse("erp:warehouse"))
        self.assertEqual(resp.status_code, 302)

    def test_management_can_decide_approvals(self):
        mgmt = User.objects.create_user(
            username="iso_mgmt", email="iso_m@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.assertTrue(can_decide_approvals(mgmt))
        self.assertFalse(can_decide_approvals(self.sales))

    def test_sales_reception_api_denied(self):
        self.client.force_login(self.sales)
        resp = self.client.get("/api/reception/today/")
        self.assertEqual(resp.status_code, 403)
        body = resp.json()
        self.assertEqual(body.get("error", {}).get("code"), "forbidden")
