"""Rəhbərlik gecikmə / davamiyyət hesabatı — hədəfli qəbul testləri."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.rbac.services import seed_rbac_catalog
from apps.residents.attendance import (
    DEFAULT_SCHEDULE_NOTE,
    STATUS_COMPLETE,
    STATUS_INCOMPLETE_NO_EXIT,
    STATUS_OPEN_TODAY,
    STATUS_REST,
    compute_day_attendance,
    employee_period_report,
    format_late,
    is_building_perimeter_reader,
    late_employees_for_day,
    schedule_for_day,
    whatsapp_week_summary_text,
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


def _evt(emp, day, hh, mm, etype, *, reader="F1TurIN", ss=0, result=AccessResult.GRANTED):
    if etype == AccessEventType.OUT:
        if "OUT" not in (reader or "").upper():
            reader = "F1TurBack_OUT"
    return AccessEvent.objects.create(
        employee=emp,
        employee_name=emp.full_name,
        card_number=emp.card_number or "100",
        company_id=emp.company_id,
        company_name=emp.company.name,
        event_type=etype,
        result=result,
        occurred_at=_aware(day, hh, mm, ss),
        reader_name=reader,
    )


@override_settings(TIME_ZONE="Asia/Baku")
class AttendanceCalculationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.cp = ResidentCompany.objects.create(
            name="City Point", slug="city-point", is_internal=True, portal_active=False
        )
        cls.resident_co = ResidentCompany.objects.create(
            name="Tenant Co", slug="tenant-a", is_internal=False, portal_active=True
        )
        cls.emp = ResidentEmployee.objects.create(
            company=cls.cp, full_name="Aygun Test", card_number="9001", is_active=True
        )
        cls.other = ResidentEmployee.objects.create(
            company=cls.cp, full_name="Bahruz Digər", card_number="9002", is_active=True
        )
        cls.tenant_emp = ResidentEmployee.objects.create(
            company=cls.resident_co, full_name="Rezident İşçi", card_number="8001", is_active=True
        )
        cls.day = date(2026, 11, 24)  # Tuesday

    def test_on_time_and_late_thresholds(self):
        # 08:55 → on time
        e1 = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 8, 55),
                reader_name="F1TurIN",
            )
        ]
        a = compute_day_attendance(employee=self.emp, day=self.day, events=e1)
        self.assertFalse(a.is_late)
        self.assertEqual(a.late_label, "—")

        # 09:00 exact → on time
        e2 = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 9, 0, 0),
                reader_name="F1TurIN",
            )
        ]
        a2 = compute_day_attendance(employee=self.emp, day=self.day, events=e2)
        self.assertFalse(a2.is_late)

        # 09:00:01 → <1 dəq (not "0 dəq")
        e3 = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 9, 0, 1),
                reader_name="F1TurIN",
            )
        ]
        a3 = compute_day_attendance(employee=self.emp, day=self.day, events=e3)
        self.assertTrue(a3.is_late)
        self.assertEqual(a3.late_label, "<1 dəq")
        self.assertNotEqual(format_late(a3.late_seconds), "0 dəq")

        # 09:12 → 12 dəq
        e4 = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 9, 12),
                reader_name="F1TurIN",
            )
        ]
        a4 = compute_day_attendance(employee=self.emp, day=self.day, events=e4)
        self.assertEqual(a4.late_label, "12 dəq")
        self.assertEqual(a4.late_minutes_floor, 12)

    def test_split_day_presence_and_late(self):
        events = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 9, 12),
                reader_name="F1TurIN",
            ),
            SimpleNamespace(
                event_type=AccessEventType.OUT,
                occurred_at=_aware(self.day, 13, 0),
                reader_name="F1TurBack_OUT",
            ),
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 14, 0),
                reader_name="F1TurIN",
            ),
            SimpleNamespace(
                event_type=AccessEventType.OUT,
                occurred_at=_aware(self.day, 18, 5),
                reader_name="F1TurBack_OUT",
            ),
        ]
        a = compute_day_attendance(employee=self.emp, day=self.day, events=events)
        # İlk giriş 09:12 → son çıxış 18:05 = 8 saat 53 dəq
        self.assertEqual(a.presence_seconds, 8 * 3600 + 53 * 60)
        self.assertEqual(a.presence_label, "8 saat 53 dəq")
        self.assertEqual(a.late_label, "12 dəq")
        self.assertEqual(a.status, STATUS_COMPLETE)
        self.assertTrue(a.is_late)

    def test_presence_matches_displayed_hhmm(self):
        """09:10:40 → 18:03:20 ekranda 09:10–18:03 → 8 saat 53 dəq."""
        events = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 9, 10, 40),
                reader_name="F1TurIN",
            ),
            SimpleNamespace(
                event_type=AccessEventType.OUT,
                occurred_at=_aware(self.day, 18, 3, 20),
                reader_name="F1TurBack_OUT",
            ),
        ]
        a = compute_day_attendance(employee=self.emp, day=self.day, events=events)
        self.assertEqual(a.presence_label, "8 saat 53 dəq")
        self.assertEqual(a.presence_seconds, 8 * 3600 + 53 * 60)

    def test_lunch_return_does_not_create_late(self):
        events = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 8, 55),
                reader_name="F1TurIN",
            ),
            SimpleNamespace(
                event_type=AccessEventType.OUT,
                occurred_at=_aware(self.day, 13, 0),
                reader_name="F1TurBack_OUT",
            ),
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 14, 10),
                reader_name="F1TurIN",
            ),
            SimpleNamespace(
                event_type=AccessEventType.OUT,
                occurred_at=_aware(self.day, 18, 0),
                reader_name="F1TurBack_OUT",
            ),
        ]
        a = compute_day_attendance(employee=self.emp, day=self.day, events=events)
        self.assertFalse(a.is_late)
        self.assertEqual(a.late_label, "—")

    def test_shaft_and_duplicate_ignored(self):
        events = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 9, 12, 0),
                reader_name="F1TurIN",
            ),
            # near-duplicate
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 9, 12, 1),
                reader_name="F1TurIN",
            ),
            # shaft — ignored
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(self.day, 10, 0),
                reader_name="F3ShaftDoor",
            ),
            SimpleNamespace(
                event_type=AccessEventType.OUT,
                occurred_at=_aware(self.day, 18, 0),
                reader_name="F1TurBack_OUT",
            ),
        ]
        self.assertFalse(is_building_perimeter_reader("F3ShaftDoor"))
        a = compute_day_attendance(employee=self.emp, day=self.day, events=events)
        self.assertEqual(a.late_label, "12 dəq")
        # Presence from first IN 09:12 to 18:00 = 8h48m (duplicate collapsed)
        self.assertEqual(a.presence_seconds, 8 * 3600 + 48 * 60)

    def test_missing_exit_past_day_not_filled(self):
        past = date(2026, 11, 20)
        events = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(past, 9, 5),
                reader_name="F1TurIN",
            )
        ]
        a = compute_day_attendance(employee=self.emp, day=past, events=events)
        self.assertEqual(a.status, STATUS_INCOMPLETE_NO_EXIT)
        self.assertIsNone(a.last_out)
        self.assertEqual(a.presence_seconds, 0)

    def test_late_list_excludes_residents_and_sorts(self):
        day = self.day
        _evt(self.emp, day, 9, 30, AccessEventType.IN)
        _evt(self.other, day, 9, 15, AccessEventType.IN)
        _evt(self.tenant_emp, day, 10, 0, AccessEventType.IN)
        rows, count, _note, _ = late_employees_for_day(day=day, roster="active")
        self.assertEqual(count, 2)
        self.assertEqual(rows[0]["employee"].pk, self.emp.pk)  # 30 dəq > 15 dəq
        self.assertEqual(rows[1]["employee"].pk, self.other.pk)
        ids = {r["employee"].pk for r in rows}
        self.assertNotIn(self.tenant_emp.pk, ids)

    def test_whatsapp_preview_is_personal(self):
        day = self.day
        _evt(self.emp, day, 9, 12, AccessEventType.IN)
        _evt(self.emp, day, 18, 0, AccessEventType.OUT)
        _evt(self.other, day, 9, 40, AccessEventType.IN)
        start, _ = week_bounds(day)
        payload = whatsapp_week_summary_text(employee=self.emp, week_start=start)
        self.assertIn(self.emp.full_name, payload["text"])
        self.assertNotIn(self.other.full_name, payload["text"])
        self.assertFalse(payload["sent"])
        self.assertIn(str(self.emp.pk), payload["dedupe_key"])

    def test_period_summary_one_late_day(self):
        day = self.day
        _evt(self.emp, day, 9, 12, AccessEventType.IN, reader="F1TurIN")
        _evt(self.emp, day, 13, 0, AccessEventType.OUT, reader="F1TurBack_OUT")
        _evt(self.emp, day, 14, 0, AccessEventType.IN, reader="F1TurIN")
        _evt(self.emp, day, 18, 5, AccessEventType.OUT, reader="F1TurBack_OUT")
        report = employee_period_report(
            employee=self.emp, date_from=day, date_to=day
        )
        self.assertEqual(report["summary"].late_days, 1)
        self.assertEqual(report["summary"].days_with_entry, 1)
        self.assertEqual(report["rows"][0].presence_seconds, 8 * 3600 + 53 * 60)

    def test_saturday_starts_at_10_sunday_is_rest(self):
        saturday = date(2026, 11, 21)  # Şənbə
        sunday = date(2026, 11, 22)  # Bazar

        sat_sched = schedule_for_day(employee=self.emp, day=saturday)
        self.assertFalse(sat_sched.is_rest)
        self.assertEqual(timezone.localtime(sat_sched.expected_start).time().hour, 10)
        self.assertEqual(timezone.localtime(sat_sched.expected_end).time().hour, 15)

        # 09:50 şənbə — hələ gecikmə deyil (10:00 qədər)
        early = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(saturday, 9, 50),
                reader_name="F1TurIN",
            ),
            SimpleNamespace(
                event_type=AccessEventType.OUT,
                occurred_at=_aware(saturday, 15, 0),
                reader_name="F1TurBack_OUT",
            ),
        ]
        a_early = compute_day_attendance(employee=self.emp, day=saturday, events=early)
        self.assertFalse(a_early.is_late)
        self.assertEqual(a_early.status, STATUS_COMPLETE)

        # 10:12 şənbə — 12 dəq gecikmə
        late = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(saturday, 10, 12),
                reader_name="F1TurIN",
            ),
            SimpleNamespace(
                event_type=AccessEventType.OUT,
                occurred_at=_aware(saturday, 15, 5),
                reader_name="F1TurBack_OUT",
            ),
        ]
        a_late = compute_day_attendance(employee=self.emp, day=saturday, events=late)
        self.assertTrue(a_late.is_late)
        self.assertEqual(a_late.late_label, "12 dəq")

        # Bazar — istirahət, 11:00 gəliş belə gecikmə sayılmır
        sun_punch = [
            SimpleNamespace(
                event_type=AccessEventType.IN,
                occurred_at=_aware(sunday, 11, 0),
                reader_name="F1TurIN",
            ),
            SimpleNamespace(
                event_type=AccessEventType.OUT,
                occurred_at=_aware(sunday, 14, 0),
                reader_name="F1TurBack_OUT",
            ),
        ]
        a_sun = compute_day_attendance(employee=self.emp, day=sunday, events=sun_punch)
        self.assertEqual(a_sun.status, STATUS_REST)
        self.assertFalse(a_sun.is_late)
        self.assertEqual(a_sun.late_label, "—")

        a_sun_empty = compute_day_attendance(employee=self.emp, day=sunday, events=[])
        self.assertEqual(a_sun_empty.status, STATUS_REST)
        self.assertFalse(a_sun_empty.is_late)

        _evt(self.emp, saturday, 10, 12, AccessEventType.IN)
        _evt(self.emp, saturday, 15, 5, AccessEventType.OUT)
        _evt(self.emp, sunday, 11, 0, AccessEventType.IN)
        _evt(self.emp, sunday, 14, 0, AccessEventType.OUT)
        report = employee_period_report(
            employee=self.emp, date_from=saturday, date_to=sunday
        )
        self.assertEqual(report["schedule_note"], DEFAULT_SCHEDULE_NOTE)
        self.assertIn("Şənbə: 10:00–15:00", report["schedule_note"])
        # Bazar istirahət — gecikmə və iş günü cəminə düşmür
        self.assertEqual(report["summary"].late_days, 1)
        self.assertEqual(report["summary"].days_with_entry, 1)
        sun_row = next(r for r in report["rows"] if r.day == sunday)
        self.assertEqual(sun_row.status, STATUS_REST)


@override_settings(TIME_ZONE="Asia/Baku")
class AttendanceAclHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.cp = ResidentCompany.objects.create(
            name="City Point", slug="city-point", is_internal=True
        )
        cls.emp = ResidentEmployee.objects.create(
            company=cls.cp, full_name="HR Emp", card_number="7001", is_active=True
        )
        cls.mgmt = User.objects.create_user(
            username="att-mgmt",
            email="att-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        cls.sec = User.objects.create_user(
            username="att-sec",
            email="att-sec@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
        )
        cls.res = User.objects.create_user(
            username="att-res",
            email="att-res@test.az",
            password="x",
            role=Role.RESIDENT_USER,
        )

    def test_management_late_list_and_security_denied(self):
        day = timezone.localdate()
        _evt(self.emp, day, 9, 20, AccessEventType.IN)
        client = Client()
        client.force_login(self.mgmt)
        url = reverse("erp:internal_staff_access")
        page = client.get(url, {"late": "1", "date": day.isoformat()})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Bu gün gecikənlər")
        self.assertContains(page, self.emp.full_name)
        detail = client.get(
            reverse("erp:internal_staff_access_detail", kwargs={"pk": self.emp.pk}),
            {"range": "week"},
        )
        self.assertEqual(detail.status_code, 200)
        wa = client.get(
            reverse("erp:internal_staff_whatsapp_preview", kwargs={"pk": self.emp.pk})
        )
        self.assertEqual(wa.status_code, 200)
        self.assertContains(wa, "Canlı WhatsApp göndərişi deaktivdir")

        client.force_login(self.sec)
        self.assertIn(client.get(url).status_code, (302, 403))
        client.force_login(self.res)
        self.assertIn(client.get(url).status_code, (302, 403))
        self.assertIn(
            client.get(
                reverse("erp:internal_staff_attendance_export", kwargs={"pk": self.emp.pk})
            ).status_code,
            (302, 403),
        )
