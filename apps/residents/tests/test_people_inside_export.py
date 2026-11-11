from datetime import datetime
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import Role
from apps.reception.models import Guest, GuestVisit, VisitStatus
from apps.residents.models import AccessEvent, AccessEventType, ResidentCompany, ResidentEmployee
from apps.residents.people_inside_export import (
    build_people_inside_xlsx,
    group_people_inside_by_company,
    people_inside_snapshot,
    people_inside_xlsx_filename,
)

User = get_user_model()


class PeopleInsideExportTests(TestCase):
    def setUp(self):
        self.company_b = ResidentCompany.objects.create(
            name="Beta Soft", slug="beta-soft", portal_active=True
        )
        self.company_a = ResidentCompany.objects.create(
            name="Alpha Labs", slug="alpha-labs", portal_active=True
        )
        today = timezone.localdate()
        in_at = timezone.make_aware(datetime.combine(today, datetime.strptime("09:00", "%H:%M").time()))

        self.emp_b = ResidentEmployee.objects.create(
            company=self.company_b,
            full_name="Zeynab Beta",
            card_number="2001",
            is_active=True,
        )
        self.emp_a = ResidentEmployee.objects.create(
            company=self.company_a,
            full_name="Anar Alpha",
            card_number="1001",
            is_active=True,
        )
        for emp in (self.emp_a, self.emp_b):
            AccessEvent.objects.create(
                employee=emp,
                event_type=AccessEventType.IN,
                occurred_at=in_at,
                employee_name=emp.full_name,
                card_number=emp.card_number,
            )

        guest = Guest.objects.create(first_name="Qonaq", last_name="Alpha")
        GuestVisit.objects.create(
            guest=guest,
            company=self.company_a,
            status=VisitStatus.INSIDE,
            scheduled_for=today,
            check_in_at=in_at,
        )
        self.today = today

        self.admin = User.objects.create_user(
            username="inside-admin",
            email="inside-admin@example.com",
            password="pass",
            role=Role.ADMIN,
        )
        self.security = User.objects.create_user(
            username="inside-sec",
            email="inside-sec@example.com",
            password="pass",
            role=Role.SECURITY,
        )

    def test_group_companies_alpha_employees_before_guests(self):
        employees, guests, _ = people_inside_snapshot(self.today)
        groups = group_people_inside_by_company(employees, guests)
        self.assertEqual([name for name, _ in groups], ["Alpha Labs", "Beta Soft"])
        alpha_rows = groups[0][1]
        self.assertEqual(alpha_rows[0]["kind"], "employee")
        self.assertEqual(alpha_rows[0]["name"], "Anar Alpha")
        self.assertEqual(alpha_rows[1]["kind"], "guest")
        self.assertIn("Qonaq", alpha_rows[1]["name"])

    def test_xlsx_layout_and_company_blocks(self):
        employees, guests, today = people_inside_snapshot(self.today)
        payload = build_people_inside_xlsx(employees, guests, report_date=today)
        wb = load_workbook(BytesIO(payload))
        ws = wb.active
        self.assertEqual(ws.title, "Binada olanlar")
        self.assertRegex(ws["A1"].value or "", r"^Binada olanlar — \d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}$")
        self.assertIn("Yüklənmə saatı:", ws["A2"].value or "")
        self.assertRegex(ws["A2"].value or "", r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}")
        values = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
        company_heads = [v for v in values if isinstance(v, str) and v.startswith("Alpha Labs")]
        self.assertTrue(company_heads)
        alpha_idx = values.index(company_heads[0])
        beta_heads = [v for v in values if isinstance(v, str) and v.startswith("Beta Soft")]
        self.assertTrue(beta_heads)
        beta_idx = values.index(beta_heads[0])
        self.assertLess(alpha_idx, beta_idx)
        self.assertRegex(
            people_inside_xlsx_filename(today),
            rf"^binada-olanlar-{today.isoformat()}_\d{{2}}-\d{{2}}-\d{{2}}\.xlsx$",
        )

    def test_empty_snapshot_still_builds_xlsx(self):
        AccessEvent.objects.all().delete()
        GuestVisit.objects.all().delete()
        employees, guests, today = people_inside_snapshot(self.today)
        self.assertEqual(employees, [])
        self.assertEqual(guests, [])
        payload = build_people_inside_xlsx(employees, guests, report_date=today)
        wb = load_workbook(BytesIO(payload))
        sheet_text = " ".join(
            str(wb.active.cell(row=r, column=1).value or "") for r in range(1, 8)
        ).lower()
        self.assertIn("heç kim", sheet_text)

    def test_erp_and_security_export_endpoints(self):
        client = Client()
        client.force_login(self.admin)
        erp = client.get(reverse("erp:people_inside_export"))
        self.assertEqual(erp.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            erp["Content-Type"],
        )
        self.assertIn("binada-olanlar-", erp["Content-Disposition"])

        client.force_login(self.security)
        sec = client.get(reverse("security:people_inside_export"))
        self.assertEqual(sec.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            sec["Content-Type"],
        )
