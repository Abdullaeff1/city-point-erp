"""Smoke: internal-staff attendance routes reverse + render without NoReverseMatch."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import NoReverseMatch, reverse

from apps.accounts.models import Role
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import ResidentCompany, ResidentEmployee

User = get_user_model()


class InternalStaffAttendanceUrlSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.company = ResidentCompany.objects.create(
            name="City Point", slug="city-point", is_internal=True, portal_active=False
        )
        cls.emp = ResidentEmployee.objects.create(
            company=cls.company, full_name="URL Smoke", card_number="77001", is_active=True
        )
        cls.admin = User.objects.create_user(
            username="admin_url_smoke",
            email="admin_url_smoke@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
        )

    def test_named_routes_reverse(self):
        cases = [
            ("erp:internal_staff_access", {}),
            ("erp:internal_staff_access_export", {}),
            ("erp:internal_staff_access_detail", {"pk": self.emp.pk}),
            ("erp:internal_staff_employee_export", {"pk": self.emp.pk}),
            ("erp:internal_staff_attendance_export", {"pk": self.emp.pk}),
            ("erp:internal_staff_whatsapp_preview", {"pk": self.emp.pk}),
        ]
        for name, kwargs in cases:
            try:
                url = reverse(name, kwargs=kwargs)
            except NoReverseMatch as exc:  # pragma: no cover - failure path
                self.fail(f"reverse failed for {name}: {exc}")
            self.assertTrue(url.startswith("/erp/"))

    def test_detail_and_late_pages_render(self):
        client = Client()
        client.force_login(self.admin)
        paths = [
            reverse("erp:internal_staff_access"),
            reverse("erp:internal_staff_access") + "?late=1",
            reverse("erp:internal_staff_access_detail", kwargs={"pk": self.emp.pk}),
            reverse("erp:internal_staff_access_detail", kwargs={"pk": self.emp.pk})
            + "?range=week",
            reverse("erp:internal_staff_access_detail", kwargs={"pk": self.emp.pk})
            + "?range=month",
            reverse("erp:internal_staff_whatsapp_preview", kwargs={"pk": self.emp.pk}),
            reverse("erp:internal_staff_attendance_export", kwargs={"pk": self.emp.pk})
            + "?range=week",
        ]
        for path in paths:
            resp = client.get(path)
            self.assertIn(resp.status_code, {200, 302}, msg=path)
            if resp.status_code == 200 and resp.get("Content-Type", "").startswith("text/html"):
                body = resp.content.decode("utf-8", errors="replace")
                self.assertNotIn("NoReverseMatch", body, msg=path)
