from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.integrations.axtrax_people_sync import (
    access_level_from_axtrax,
    resolve_access_level_for_row,
)
from apps.residents.models import AccessLevel, ResidentCompany, ResidentEmployee
from apps.residents.services import create_employee_card_order
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy

User = get_user_model()


class AccessLevelMappingTests(TestCase):
    def test_turn_back_flag(self):
        self.assertEqual(access_level_from_axtrax(has_turn_back=True), AccessLevel.LEVEL_2)
        self.assertEqual(access_level_from_axtrax(has_turn_back=False), AccessLevel.LEVEL_1)

    def test_group_name_back(self):
        self.assertEqual(
            access_level_from_axtrax(access_group_name="Entrance Busines +Back"),
            AccessLevel.LEVEL_2,
        )
        self.assertEqual(
            access_level_from_axtrax(access_group_name="Entrance Busines"),
            AccessLevel.LEVEL_1,
        )

    def test_row_uses_group_lookup(self):
        lookup = {6: {"name": "Entrance Busines +Back", "has_turn_back": True}}
        level = resolve_access_level_for_row({"access_group_id": 6}, lookup)
        self.assertEqual(level, AccessLevel.LEVEL_2)
        self.assertIsNone(resolve_access_level_for_row({"access_group_id": 99}, lookup))


class SecurityPortalTests(TestCase):
    def setUp(self):
        seed_ticket_taxonomy()
        self.company = ResidentCompany.objects.create(
            name="ASBC Sec", slug="asbc-sec", portal_active=True, is_internal=False
        )
        self.internal = ResidentCompany.objects.create(
            name="City Point", slug="city-point", portal_active=False, is_internal=True
        )
        self.security = User.objects.create_user(
            username="sec1",
            email="security@test.az",
            password="Pass12345!",
            role=Role.SECURITY,
        )
        self.resident = User.objects.create_user(
            username="res1",
            email="office@asbc-sec.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        self.client = Client()

    def test_security_login_lands_on_security_home(self):
        self.client.force_login(self.security)
        resp = self.client.get(reverse("post_login"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("security:home"))

    def test_security_home_ok(self):
        self.client.force_login(self.security)
        resp = self.client.get(reverse("security:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Təhlükəsizlik")

    def test_resident_blocked_from_security(self):
        self.client.force_login(self.resident)
        resp = self.client.get(reverse("security:home"))
        self.assertEqual(resp.status_code, 403)

    def test_security_blocked_from_erp(self):
        self.client.force_login(self.security)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 403)

    def test_sees_internal_and_tenant_companies(self):
        ResidentEmployee.objects.create(
            company=self.internal,
            full_name="CP Worker",
            card_number="2001",
            access_level=AccessLevel.LEVEL_2,
            is_active=True,
        )
        self.client.force_login(self.security)
        list_resp = self.client.get(reverse("security:companies"))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, self.company.name)
        self.assertContains(list_resp, "City Point")

        emp_resp = self.client.get(reverse("security:company_employees", args=[self.internal.pk]))
        self.assertEqual(emp_resp.status_code, 200)
        self.assertContains(emp_resp, "CP Worker")
        self.assertNotContains(emp_resp, "employee_set_level")

    def test_manual_level_endpoint_gone(self):
        emp = ResidentEmployee.objects.create(
            company=self.company,
            full_name="Level Person",
            card_number="1001",
            access_level=AccessLevel.LEVEL_1,
            is_active=True,
        )
        self.client.force_login(self.security)
        resp = self.client.post(
            f"/security/employees/{emp.pk}/level/",
            {"access_level": AccessLevel.LEVEL_2},
        )
        self.assertEqual(resp.status_code, 404)
        emp.refresh_from_db()
        self.assertEqual(emp.access_level, AccessLevel.LEVEL_1)

    def test_card_order_ticket_visible(self):
        emp, ticket = create_employee_card_order(
            company=self.company,
            requester=self.resident,
            full_name="Kart İşçi",
            id_document=SimpleUploadedFile("id.pdf", b"%PDF", content_type="application/pdf"),
            access_level=AccessLevel.LEVEL_2,
        )
        self.assertEqual(emp.access_level, AccessLevel.LEVEL_2)
        self.client.force_login(self.security)
        tickets = self.client.get(reverse("security:tickets") + "?tab=card-orders")
        self.assertEqual(tickets.status_code, 200)
        self.assertContains(tickets, ticket.code)
        detail = self.client.get(reverse("security:ticket_detail", args=[ticket.code]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Səviyyə 2")
