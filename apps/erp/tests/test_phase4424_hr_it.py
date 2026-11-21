"""Phase 4.4.2.4 — HR attendance + IT staff directory operator workflows."""

from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import Role
from apps.accounts.nav import build_nav_flags
from apps.erp.department_dashboards import build_hr_dashboard, build_it_dashboard
from apps.erp.it_access import can_access_erp_audit
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import AccessEvent, AccessEventType, ResidentCompany, ResidentEmployee

User = get_user_model()


class Phase4424HrItWorkflowTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.admin = User.objects.create_user(
            username="p4424-adm",
            email="p4424-adm@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.mgmt = User.objects.create_user(
            username="p4424-mgmt",
            email="p4424-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.desk = User.objects.create_user(
            username="p4424-desk",
            email="p4424-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="p4424-sales",
            email="p4424-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        self.resident = User.objects.create_user(
            username="p4424-res",
            email="p4424-res@test.az",
            password="x",
            role=Role.RESIDENT_USER,
        )
        self.cp = ResidentCompany.objects.create(
            name="City Point", slug="city-point", is_internal=True, status="active"
        )
        self.other = ResidentCompany.objects.create(
            name="Tenant Co", slug="tenant-4424", is_internal=False, status="active"
        )
        self.emp = ResidentEmployee.objects.create(
            company=self.cp, full_name="Aygun HR", card_number="HR100", is_active=True
        )
        self.foreign = ResidentEmployee.objects.create(
            company=self.other, full_name="Foreign Emp", card_number="X1", is_active=True
        )
        AccessEvent.objects.create(
            employee=self.emp,
            event_type=AccessEventType.IN,
            occurred_at=timezone.now(),
            employee_name=self.emp.full_name,
            card_number=self.emp.card_number,
        )

    def test_A_hr_operator_completes_attendance_workflow(self):
        self.client.force_login(self.mgmt)
        dash = self.client.get(reverse("erp:hr_dashboard"))
        self.assertEqual(dash.status_code, 200)
        self.assertContains(dash, reverse("erp:internal_staff_access"))

        listing = self.client.get(reverse("erp:internal_staff_access"), {"q": "Aygun"})
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "Aygun HR")
        self.assertContains(
            listing, reverse("erp:internal_staff_access_detail", kwargs={"pk": self.emp.pk})
        )

        detail = self.client.get(
            reverse("erp:internal_staff_access_detail", kwargs={"pk": self.emp.pk})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Aygun HR")
        self.assertContains(detail, reverse("erp:hr_dashboard"))

        export = self.client.get(
            reverse("erp:internal_staff_access_export"), {"range": "month"}
        )
        self.assertEqual(export.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            export["Content-Type"],
        )

    def test_B_it_operator_completes_staff_directory_workflow(self):
        self.client.force_login(self.admin)
        dash = self.client.get(reverse("erp:it_dashboard"))
        self.assertEqual(dash.status_code, 200)
        self.assertContains(dash, reverse("erp:staff_users"))
        self.assertContains(dash, "/admin/accounts/user/")

        listing = self.client.get(reverse("erp:staff_users"), {"q": "p4424-desk"})
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "p4424-desk@test.az")
        self.assertNotContains(listing, "p4424-res@test.az")

        detail = self.client.get(
            reverse("erp:staff_user_detail", kwargs={"pk": self.desk.pk})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, self.desk.email)
        self.assertContains(detail, "/admin/accounts/user/")

        audit = self.client.get(reverse("erp:audit"))
        self.assertEqual(audit.status_code, 200)

    def test_C_dashboard_counts_match_lists(self):
        board = build_hr_dashboard(self.mgmt)
        internal_kpi = next(k for k in board["kpis"] if "Daxili" in str(k["label"]))
        self.assertEqual(internal_kpi["value"], 1)
        self.assertEqual(internal_kpi["url"], reverse("erp:internal_staff_access"))

        it_board = build_it_dashboard(self.admin)
        active_kpi = next(k for k in it_board["kpis"] if "Aktiv" in str(k["label"]))
        self.assertGreaterEqual(active_kpi["value"], 4)
        self.assertEqual(active_kpi["url"], reverse("erp:staff_users"))

    def test_D_viewer_cannot_write_reserved_actions(self):
        # Management: HR read/export OK; staff directory read OK; audit write path N/A;
        # cannot open Admin-gated audit timeline.
        from apps.accounts.test_utils import assert_soft_denied

        self.assertFalse(can_access_erp_audit(self.mgmt))
        self.client.force_login(self.mgmt)
        assert_soft_denied(
            self,
            self.client,
            self.client.get(reverse("erp:audit")),
            self.mgmt,
            expected_url=reverse("erp:dashboard"),
            protected_markers=('id="audit-log"',),
        )
        # Staff directory is read-only for Management (no user.admin → no Admin mutate link).
        resp = self.client.get(reverse("erp:staff_user_detail", kwargs={"pk": self.desk.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Django Admin-də aç")
        self.assertNotContains(resp, "/admin/accounts/user/")

    def test_E_unauthorized_department_and_resident_blocked(self):
        self.client.force_login(self.desk)
        self.assertIn(self.client.get(reverse("erp:hr_dashboard")).status_code, (302, 403))
        self.assertIn(
            self.client.get(reverse("erp:internal_staff_access")).status_code, (302, 403)
        )
        self.assertIn(self.client.get(reverse("erp:staff_users")).status_code, (302, 403))

        self.client.force_login(self.sales)
        self.assertIn(self.client.get(reverse("erp:hr_dashboard")).status_code, (302, 403))
        self.assertIn(self.client.get(reverse("erp:it_dashboard")).status_code, (302, 403))

        self.client.force_login(self.resident)
        self.assertIn(self.client.get(reverse("erp:hr_dashboard")).status_code, (302, 403))
        self.assertIn(self.client.get(reverse("erp:staff_users")).status_code, (302, 403))

    def test_F_forged_related_ids_rejected(self):
        self.client.force_login(self.mgmt)
        # Foreign resident-company employee must not open via HR detail.
        resp = self.client.get(
            reverse("erp:internal_staff_access_detail", kwargs={"pk": self.foreign.pk})
        )
        self.assertEqual(resp.status_code, 404)

        # Resident portal user must not appear in staff directory / detail.
        self.client.force_login(self.admin)
        resp = self.client.get(
            reverse("erp:staff_user_detail", kwargs={"pk": self.resident.pk})
        )
        self.assertEqual(resp.status_code, 404)

    def test_G_invalid_search_preserves_empty_authorized_list(self):
        self.client.force_login(self.mgmt)
        resp = self.client.get(reverse("erp:internal_staff_access"), {"q": "zzz-no-match"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Axtarışa uyğun işçi yoxdur")
        self.assertEqual(resp.context["total_employees"], 0)

    def test_H_repeated_export_stable(self):
        self.client.force_login(self.admin)
        url = reverse("erp:internal_staff_employee_export", kwargs={"pk": self.emp.pk})
        r1 = self.client.get(url, {"range": "month"})
        r2 = self.client.get(url, {"range": "month"})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.content, r2.content)

    def test_I_deactivation_preserves_history_visibility(self):
        self.emp.mark_inactive()
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.is_active)
        self.assertIsNotNone(self.emp.deactivated_at)
        self.client.force_login(self.mgmt)
        former = self.client.get(reverse("erp:internal_staff_access"), {"roster": "former"})
        self.assertEqual(former.status_code, 200)
        self.assertContains(former, "Aygun HR")
        detail = self.client.get(
            reverse("erp:internal_staff_access_detail", kwargs={"pk": self.emp.pk})
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Keçmiş işçi")

    def test_J_management_hub_hr_points_to_dashboard(self):
        self.client.force_login(self.mgmt)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        hr = next(m for m in resp.context["hub_modules"] if m["key"] == "hr")
        self.assertEqual(hr["url"], reverse("erp:hr_dashboard"))

    def test_K_operator_entry_points_and_redirects(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("erp:dashboard")).url, reverse("erp:it_dashboard"))
        self.assertEqual(self.client.get(reverse("erp:it_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("erp:hr_dashboard")).status_code, 200)

        self.client.force_login(self.mgmt)
        # Management may open IT dashboard via audit.view, but not the Admin audit page.
        self.assertEqual(self.client.get(reverse("erp:it_dashboard")).status_code, 200)
        board = build_it_dashboard(self.mgmt)
        labels = [str(k["label"]) for k in board["kpis"]]
        self.assertNotIn("Audit qeyd", labels)
        self.assertTrue(any("İstifadəçi" in str(a.get("label", "")) for a in board["quick_actions"]))
        # Misleading nav: Management must not see Audit sidebar link.
        flags = build_nav_flags(self.mgmt)
        self.assertFalse(flags["nav_audit"])
        self.assertTrue(flags["nav_staff_users"])
        from apps.accounts.test_utils import assert_soft_denied

        assert_soft_denied(
            self,
            self.client,
            self.client.get(reverse("erp:audit")),
            self.mgmt,
            expected_url=reverse("erp:dashboard"),
            protected_markers=('id="audit-log"',),
        )


class Phase4424AccessBoundaryAndExportTests(TestCase):
    """Closeout: cross-route CP visibility + export fidelity."""

    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.admin = User.objects.create_user(
            username="p4424b-adm",
            email="p4424b-adm@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.mgmt = User.objects.create_user(
            username="p4424b-mgmt",
            email="p4424b-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.desk = User.objects.create_user(
            username="p4424b-desk",
            email="p4424b-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.security = User.objects.create_user(
            username="p4424b-sec",
            email="p4424b-sec@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
        )
        self.cp = ResidentCompany.objects.create(
            name="City Point", slug="city-point", is_internal=True, status="active"
        )
        self.tenant = ResidentCompany.objects.create(
            name="Tenant B", slug="tenant-b-4424", is_internal=False, status="active"
        )
        self.emp_a = ResidentEmployee.objects.create(
            company=self.cp, full_name="Nigar Active", card_number="A1", is_active=True
        )
        self.emp_b = ResidentEmployee.objects.create(
            company=self.cp, full_name="Elchin Active", card_number="A2", is_active=True
        )
        self.former = ResidentEmployee.objects.create(
            company=self.cp, full_name="Former Staff", card_number="F1", is_active=True
        )
        self.former.mark_inactive()
        self.tenant_emp = ResidentEmployee.objects.create(
            company=self.tenant, full_name="Tenant Worker", card_number="T1", is_active=True
        )
        day = timezone.localdate()
        older = day - timedelta(days=3)
        for emp, hhmm in ((self.emp_a, "09:00"), (self.emp_b, "10:30"), (self.former, "08:15")):
            AccessEvent.objects.create(
                employee=emp,
                event_type=AccessEventType.IN,
                occurred_at=timezone.make_aware(
                    datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())
                ),
                employee_name=emp.full_name,
                card_number=emp.card_number,
            )
        AccessEvent.objects.create(
            employee=self.former,
            event_type=AccessEventType.IN,
            occurred_at=timezone.make_aware(
                datetime.combine(older, datetime.strptime("09:00", "%H:%M").time())
            ),
            employee_name=self.former.full_name,
            card_number=self.former.card_number,
        )
        AccessEvent.objects.create(
            employee=self.tenant_emp,
            event_type=AccessEventType.IN,
            occurred_at=timezone.now(),
            employee_name=self.tenant_emp.full_name,
            card_number=self.tenant_emp.card_number,
        )

    def test_people_inside_requires_security_or_hr(self):
        self.client.force_login(self.desk)
        self.assertIn(self.client.get(reverse("erp:people_inside")).status_code, (302, 403))
        self.assertIn(
            self.client.get(
                reverse("erp:people_inside_detail", kwargs={"pk": self.emp_a.pk})
            ).status_code,
            (302, 403),
        )
        self.assertIn(self.client.get(reverse("erp:people_inside_export")).status_code, (302, 403))

        self.client.force_login(self.mgmt)
        self.assertEqual(self.client.get(reverse("erp:people_inside")).status_code, 200)
        self.assertContains(self.client.get(reverse("erp:people_inside")), "Nigar Active")

    def test_security_keeps_cp_attendance_operational_access(self):
        self.client.force_login(self.security)
        resp = self.client.get(
            reverse("security:company_employees", kwargs={"pk": self.cp.pk})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Nigar Active")
        export = self.client.get(
            reverse("security:company_access_export", kwargs={"pk": self.cp.pk}),
            {"range": "month"},
        )
        self.assertEqual(export.status_code, 200)

    def test_resident_company_routes_exclude_city_point(self):
        self.client.force_login(self.mgmt)
        self.assertEqual(
            self.client.get(reverse("erp:resident_detail", kwargs={"slug": "city-point"})).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("erp:resident_detail", kwargs={"slug": self.tenant.slug})
            ).status_code,
            200,
        )

    def test_export_roster_and_employee_scope(self):
        self.client.force_login(self.admin)
        # Active roster must not include former or tenant employee names in workbook.
        resp = self.client.get(
            reverse("erp:internal_staff_access_export"),
            {"range": "custom", "from": timezone.localdate().isoformat(), "to": timezone.localdate().isoformat(), "roster": "active"},
        )
        self.assertEqual(resp.status_code, 200)
        wb = load_workbook(BytesIO(resp.content))
        text = " ".join(
            str(c.value or "")
            for row in wb.active.iter_rows(min_row=1, max_row=40, max_col=6)
            for c in row
        )
        self.assertIn("Nigar", text)
        self.assertIn("Elchin", text)
        self.assertNotIn("Former Staff", text)
        self.assertNotIn("Tenant Worker", text)

        # Single-employee export only that person.
        one = self.client.get(
            reverse("erp:internal_staff_employee_export", kwargs={"pk": self.emp_a.pk}),
            {"range": "today", "date": timezone.localdate().isoformat()},
        )
        self.assertEqual(one.status_code, 200)
        wb1 = load_workbook(BytesIO(one.content))
        text1 = " ".join(
            str(c.value or "")
            for row in wb1.active.iter_rows(min_row=1, max_row=20, max_col=6)
            for c in row
        )
        self.assertIn("Nigar", text1)
        self.assertNotIn("Elchin", text1)

        # Former history remains exportable via former roster / employee export.
        former_list = self.client.get(
            reverse("erp:internal_staff_access"), {"roster": "former"}
        )
        self.assertContains(former_list, "Former Staff")
        former_x = self.client.get(
            reverse("erp:internal_staff_employee_export", kwargs={"pk": self.former.pk}),
            {
                "range": "custom",
                "from": (timezone.localdate() - timedelta(days=7)).isoformat(),
                "to": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(former_x.status_code, 200)
        wb_f = load_workbook(BytesIO(former_x.content))
        text_f = " ".join(
            str(c.value or "")
            for row in wb_f.active.iter_rows(min_row=1, max_row=30, max_col=6)
            for c in row
        )
        self.assertIn("Former", text_f)
        # Workbook includes an actual time cell for the older punch.
        times = [
            c.value
            for row in wb_f.active.iter_rows(min_row=1, max_row=30, max_col=6)
            for c in row
            if isinstance(c.value, str) and ":" in c.value
        ]
        self.assertTrue(any("09:00" in t or "08:15" in t for t in times), times)
