from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.residents.services import deactivate_resident_employee

User = get_user_model()


class DeactivateEmployeeTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="Deact Co", slug="deact-co", portal_active=True, is_internal=False
        )
        self.emp = ResidentEmployee.objects.create(
            company=self.company,
            full_name="Aktiv İşçi",
            card_number="9999",
            is_active=True,
        )
        self.admin = User.objects.create_user(
            username="adm-deact",
            email="adm-deact@test.az",
            password="Pass12345!",
            role=Role.ADMIN,
            is_staff=True,
        )

    def test_service_clears_card(self):
        deactivate_resident_employee(self.emp, actor=self.admin, clear_card=True)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.is_active)
        self.assertEqual(self.emp.card_number, "")
        self.assertIsNotNone(self.emp.deactivated_at)

    def test_erp_post_deactivate(self):
        client = Client()
        client.force_login(self.admin)
        url = reverse(
            "erp:resident_employee_access",
            kwargs={"slug": self.company.slug, "pk": self.emp.pk},
        )
        resp = client.post(url, {"action": "deactivate"})
        self.assertEqual(resp.status_code, 302)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.is_active)
