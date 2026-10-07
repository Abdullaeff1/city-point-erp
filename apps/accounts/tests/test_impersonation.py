from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.impersonation import SESSION_IMPERSONATOR_ID
from apps.accounts.models import Role

User = get_user_model()


class RoleSwitchTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@citypoint.az",
            password="admin123",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.reception = User.objects.create_user(
            username="reception",
            email="reception@citypoint.az",
            password="reception123",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.security = User.objects.create_user(
            username="security",
            email="security@citypoint.az",
            password="security123",
            role=Role.SECURITY,
            is_staff=True,
        )
        self.desk = User.objects.create_user(
            username="desk",
            email="desk@citypoint.az",
            password="desk123",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.client = Client()

    def test_admin_can_switch_to_reception(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("accounts:switch_role", args=[Role.RECEPTION]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/go/")
        session = self.client.session
        self.assertEqual(session.get(SESSION_IMPERSONATOR_ID), self.admin.pk)
        # follow to confirm ERP as reception
        r2 = self.client.get("/erp/")
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, "ROLLAR")
        self.assertContains(r2, "Adminə qayıt")
        self.assertNotContains(r2, "cp-impersonation-banner")

    def test_switch_to_security_lands_on_security_portal(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:switch_role", args=[Role.SECURITY]))
        r = self.client.get("/go/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/security/"))

    def test_stop_restores_admin(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:switch_role", args=[Role.RECEPTION]))
        r = self.client.post(reverse("accounts:stop_role_preview"))
        self.assertEqual(r.status_code, 302)
        self.assertIsNone(self.client.session.get(SESSION_IMPERSONATOR_ID))
        r2 = self.client.get("/erp/")
        self.assertEqual(r2.status_code, 200)
        self.assertNotContains(r2, "Adminə qayıt")

    def test_reception_cannot_start_switch(self):
        self.client.force_login(self.reception)
        r = self.client.post(reverse("accounts:switch_role", args=[Role.SECURITY]))
        self.assertEqual(r.status_code, 403)

    def test_hop_between_roles_keeps_impersonator(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:switch_role", args=[Role.RECEPTION]))
        self.client.post(reverse("accounts:switch_role", args=[Role.SERVICE_DESK]))
        self.assertEqual(self.client.session.get(SESSION_IMPERSONATOR_ID), self.admin.pk)
        # clicking Admin role restores
        self.client.post(reverse("accounts:switch_role", args=[Role.ADMIN]))
        self.assertIsNone(self.client.session.get(SESSION_IMPERSONATOR_ID))
