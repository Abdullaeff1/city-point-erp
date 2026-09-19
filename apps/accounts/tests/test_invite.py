from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.invite import consume_invite, create_portal_invite, provision_portal_user
from apps.accounts.models import Role
from apps.residents.models import ResidentCompany

User = get_user_model()


class PortalInviteTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(name="ASBC", slug="asbc", portal_active=True)
        self.client = Client()

    def test_provision_and_accept_invite(self):
        user, raw = provision_portal_user(
            email="office@asbc.az",
            company=self.company,
            first_name="Office",
            last_name="Mgr",
        )
        self.assertEqual(user.role, Role.RESIDENT_USER)
        self.assertTrue(user.must_set_password)
        self.assertFalse(user.has_usable_password())

        url = reverse("accounts:invite_accept", kwargs={"token": raw})
        resp = self.client.post(
            url,
            {"new_password1": "SecurePass123!", "new_password2": "SecurePass123!"},
        )
        self.assertEqual(resp.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.must_set_password)
        self.assertTrue(user.check_password("SecurePass123!"))

    def test_invalid_invite(self):
        url = reverse("accounts:invite_accept", kwargs={"token": "not-a-real-token"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 400)

    def test_consume_invite_once(self):
        user, raw = provision_portal_user(email="once@asbc.az", company=self.company)
        consume_invite(raw, "SecurePass123!")
        with self.assertRaises(ValueError):
            consume_invite(raw, "OtherPass123!")

    def test_force_password_middleware(self):
        user = User.objects.create_user(
            username="force1",
            email="force@asbc.az",
            password="temp-pass-OK1",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
            must_set_password=True,
        )
        self.client.force_login(user)
        resp = self.client.get(reverse("portal:home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/force-password/", resp["Location"])
