"""İşçi kartı dövr sərhədləri + gecikmə filtri + Excel məzmunu."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import Role
from apps.rbac.services import seed_rbac_catalog
from apps.residents.attendance import (
    STATUS_INCOMPLETE_NO_EXIT,
    attendance_xlsx_bytes,
    attendance_xlsx_filename,
    employee_period_report,
    resolve_attendance_period,
    week_bounds,
)
from apps.residents.models import (
    AccessEvent,
    AccessEventType,
    AccessResult,
    ResidentCompany,
    ResidentEmployee,
)

User = get_user_model()


def _aware(day: date, hh: int, mm: int, ss: int = 0):
    return timezone.make_aware(datetime.combine(day, time(hh, mm, ss)))


def _evt(emp, day, hh, mm, etype, *, reader="F1TurIN", ss=0):
    if etype == AccessEventType.OUT and "OUT" not in (reader or "").upper():
        reader = "F1TurBack_OUT"
    return AccessEvent.objects.create(
        employee=emp,
        employee_name=emp.full_name,
        card_number=emp.card_number or "100",
        company_id=emp.company_id,
        company_name=emp.company.name,
        event_type=etype,
        result=AccessResult.GRANTED,
        occurred_at=_aware(day, hh, mm, ss),
        reader_name=reader,
    )


@override_settings(TIME_ZONE="Asia/Baku")
class AttendancePeriodBoundsTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_five_presets_and_cross_month_week(self):
        # Anchor Thursday 2026-01-01 → week Mon 2025-12-29 … Sun 2026-01-04
        req = self.rf.get("/", {"range": "week", "week_start": "2026-01-01"})
        b = resolve_attendance_period(req)
        self.assertEqual(b["preset"], "week")
        self.assertEqual(b["date_from"], date(2025, 12, 29))
        self.assertEqual(b["date_to"], date(2026, 1, 4))

        req = self.rf.get("/", {"range": "today", "date": "2026-11-27"})
        b = resolve_attendance_period(req)
        self.assertEqual(b["date_from"], date(2026, 11, 27))
        self.assertEqual(b["date_to"], date(2026, 11, 27))

        req = self.rf.get("/", {"range": "month", "year": "2026", "month": "11"})
        b = resolve_attendance_period(req)
        self.assertEqual(b["date_from"], date(2026, 11, 1))
        self.assertEqual(b["date_to"], date(2026, 11, 30))

        req = self.rf.get("/", {"range": "year", "year": "2025"})
        b = resolve_attendance_period(req)
        self.assertEqual(b["date_from"], date(2025, 1, 1))
        self.assertEqual(b["date_to"], date(2025, 12, 31))

        req = self.rf.get("/", {"range": "custom", "from": "2026-11-01", "to": "2026-11-10"})
        b = resolve_attendance_period(req)
        self.assertEqual(b["date_from"], date(2026, 11, 1))
        self.assertEqual(b["date_to"], date(2026, 11, 10))
        self.assertFalse(b["error"])

        req = self.rf.get("/", {"range": "custom", "from": "2026-11-10", "to": "2026-11-01"})
        b = resolve_attendance_period(req)
        self.assertTrue(b["error"])
        self.assertIn("Son tarix", b["error"])


@override_settings(TIME_ZONE="Asia/Baku")
class AttendanceLateFilterExcelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.cp = ResidentCompany.objects.create(
            name="City Point", slug="city-point", is_internal=True, portal_active=False
        )
        cls.emp = ResidentEmployee.objects.create(
            company=cls.cp, full_name="Sintetik İşçi", card_number="9911", is_active=True
        )
        cls.admin = User.objects.create_user(
            username="att_card_admin",
            email="att_card_admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
        )
        # On-time day (not late)
        d1 = date(2026, 11, 23)
        _evt(cls.emp, d1, 8, 55, AccessEventType.IN)
        _evt(cls.emp, d1, 18, 0, AccessEventType.OUT)
        # Late 12 dəq, missing exit
        d2 = date(2026, 11, 24)
        _evt(cls.emp, d2, 9, 12, AccessEventType.IN)
        # Late 18 dəq, complete
        d3 = date(2026, 11, 25)
        _evt(cls.emp, d3, 9, 18, AccessEventType.IN)
        _evt(cls.emp, d3, 18, 0, AccessEventType.OUT)
        # No punch day 26 — should not count as late
        cls.d1, cls.d2, cls.d3 = d1, d2, d3

    def test_late_filter_screen_and_excel_match(self):
        report = employee_period_report(
            employee=self.emp,
            date_from=date(2026, 11, 23),
            date_to=date(2026, 11, 26),
            late_only=True,
        )
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual({r.day for r in report["rows"]}, {self.d2, self.d3})
        self.assertEqual(report["summary"].late_days, 2)
        self.assertEqual(report["summary"].total_late_seconds, (12 + 18) * 60)
        self.assertEqual(report["summary_late_label"], "30 dəq")

        incomplete = next(r for r in report["rows"] if r.day == self.d2)
        self.assertEqual(incomplete.late_label, "12 dəq")
        self.assertEqual(incomplete.status, STATUS_INCOMPLETE_NO_EXIT)
        self.assertIsNone(incomplete.last_out)

        data = attendance_xlsx_bytes(
            employee=self.emp,
            date_from=date(2026, 11, 23),
            date_to=date(2026, 11, 26),
            late_only=True,
            report=report,
        )
        wb = load_workbook(BytesIO(data))
        ws = wb.active
        self.assertIn("Şöbə:", ws["A1"].value)
        self.assertIn(self.emp.full_name.split()[-1], ws["A2"].value)
        header_row = None
        for r in range(1, 30):
            if ws.cell(r, 1).value == "Tarix" and ws.cell(r, 6).value == "Gecikmə":
                header_row = r
                break
        self.assertIsNotNone(header_row)
        self.assertEqual(
            [ws.cell(header_row, c).value for c in range(1, 8)],
            ["Tarix", "Gün", "Giriş", "Çıxış", "Müddət", "Gecikmə", "Qeyd"],
        )
        dates = []
        for r in range(header_row + 1, ws.max_row + 1):
            val = ws.cell(r, 1).value
            if isinstance(val, str) and val.strip():
                dates.append(datetime.strptime(val, "%d.%m.%Y").date())
            elif isinstance(val, datetime):
                dates.append(val.date())
            elif isinstance(val, date):
                dates.append(val)
        self.assertEqual(set(dates), {self.d2, self.d3})

        def _hmm_to_minutes(val) -> float:
            if val is None or val == "":
                return 0.0
            if isinstance(val, str) and ":" in val:
                h, m = val.split(":", 1)
                return int(h) * 60 + int(m)
            raise AssertionError(f"unexpected late cell type: {type(val)} {val!r}")

        late_vals = [
            ws.cell(r, 6).value
            for r in range(header_row + 1, header_row + 1 + len(dates))
        ]
        self.assertEqual(len([v for v in late_vals if v]), 2)
        total_minutes = round(sum(_hmm_to_minutes(v) for v in late_vals))
        self.assertEqual(total_minutes, 30)
        self.assertTrue(any(ws.cell(r, 7).value for r in range(header_row + 1, header_row + 3)))

        # Sample artifact for manual review
        out_dir = Path("artifacts/attendance")
        out_dir.mkdir(parents=True, exist_ok=True)
        sample = out_dir / attendance_xlsx_filename(
            employee=self.emp,
            date_from=date(2026, 11, 23),
            date_to=date(2026, 11, 26),
            late_only=True,
        )
        sample.write_bytes(data)
        self.assertTrue(sample.exists())

    def test_late_list_has_no_excel_column_and_card_opens(self):
        client = Client()
        client.force_login(self.admin)
        list_url = reverse("erp:internal_staff_access") + "?date=2026-11-24&late=1"
        resp = client.get(list_url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Gecikənlər siyahısı", body)
        self.assertNotIn(">Excel</", body)
        detail = reverse("erp:internal_staff_access_detail", kwargs={"pk": self.emp.pk})
        self.assertIn(f"{detail}?range=today&date=2026-11-24", body)
        self.assertIn("return_late=1", body)

        card = client.get(
            detail + "?range=today&date=2026-11-24&return_late=1&return_roster=active&return_date=2026-11-24"
        )
        self.assertEqual(card.status_code, 200)
        html = card.content.decode()
        self.assertIn("Siyahıya qayıt", html)
        self.assertIn("late=1", html)
        self.assertIn("Excel yüklə", html)
        self.assertNotIn("Köhnə AxTrax Excel", html)

    def test_legacy_monthly_export_and_unauthorized(self):
        client = Client()
        client.force_login(self.admin)
        legacy = reverse("erp:internal_staff_employee_export", kwargs={"pk": self.emp.pk})
        self.assertEqual(client.get(legacy, {"range": "month"}).status_code, 200)

        sec = User.objects.create_user(
            username="sec_no_att",
            email="sec_no_att@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
        )
        client.force_login(sec)
        xlsx = reverse("erp:internal_staff_attendance_export", kwargs={"pk": self.emp.pk})
        self.assertIn(client.get(xlsx, {"range": "week"}).status_code, (302, 403))
