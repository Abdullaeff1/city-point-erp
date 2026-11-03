from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from django.test import RequestFactory

from apps.residents.access import employee_access_period_context, employee_attendance_days
from apps.residents.models import (
    AccessEvent,
    AccessEventType,
    AccessResult,
    ResidentCompany,
    ResidentEmployee,
)


class AccessCardDistinctionTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="Card Dist Co", slug="card-dist-co", portal_active=True
        )
        self.emp = ResidentEmployee.objects.create(
            company=self.company,
            full_name="Test Person",
            card_number="006109",
            is_active=True,
        )
        self.other = ResidentEmployee.objects.create(
            company=self.company,
            full_name="Former Holder",
            card_number="",
            is_active=True,
        )
        day = timezone.localdate() - timedelta(days=5)
        self.day_old = day
        self.day_new = timezone.localdate() - timedelta(days=1)

        def _at(d, hour):
            return timezone.make_aware(datetime.combine(d, datetime.min.time().replace(hour=hour)))

        # Same person used old then new card
        AccessEvent.objects.create(
            employee=self.emp,
            event_type=AccessEventType.IN,
            result=AccessResult.GRANTED,
            occurred_at=_at(self.day_old, 9),
            employee_name=self.emp.full_name,
            card_number="006297",
            company_id=self.company.pk,
            company_name=self.company.name,
        )
        AccessEvent.objects.create(
            employee=self.emp,
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=_at(self.day_old, 18),
            employee_name=self.emp.full_name,
            card_number="006297",
            company_id=self.company.pk,
            company_name=self.company.name,
        )
        AccessEvent.objects.create(
            employee=self.emp,
            event_type=AccessEventType.IN,
            result=AccessResult.GRANTED,
            occurred_at=_at(self.day_new, 9),
            employee_name=self.emp.full_name,
            card_number="006109",
            company_id=self.company.pk,
            company_name=self.company.name,
        )
        AccessEvent.objects.create(
            employee=self.emp,
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=_at(self.day_new, 12),
            employee_name=self.emp.full_name,
            card_number="006109",
            company_id=self.company.pk,
            company_name=self.company.name,
        )
        # Prior owner of 006109 — must not appear on emp
        AccessEvent.objects.create(
            employee=self.other,
            event_type=AccessEventType.IN,
            result=AccessResult.GRANTED,
            occurred_at=_at(self.day_old, 10),
            employee_name=self.other.full_name,
            card_number="006109",
            company_id=self.company.pk,
            company_name=self.company.name,
        )

    def test_empty_current_window_falls_back_to_last_month(self):
        """Stale custom/today with no punches → show previous month history."""
        today = timezone.localdate()
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        day = last_prev.replace(day=min(15, last_prev.day))

        def _at(hour):
            return timezone.make_aware(
                datetime.combine(day, datetime.min.time().replace(hour=hour))
            )

        AccessEvent.objects.create(
            employee=self.emp,
            event_type=AccessEventType.IN,
            result=AccessResult.DENIED,
            occurred_at=_at(9),
            employee_name=self.emp.full_name,
            card_number="006109",
        )
        AccessEvent.objects.create(
            employee=self.emp,
            event_type=AccessEventType.OUT,
            result=AccessResult.DENIED,
            occurred_at=_at(18),
            employee_name=self.emp.full_name,
            card_number="006109",
        )
        # Clear punches in the current month so "today" / this-month windows are empty.
        AccessEvent.objects.filter(
            employee=self.emp, occurred_at__gte=timezone.make_aware(
                datetime.combine(first_this, datetime.min.time())
            )
        ).delete()
        rf = RequestFactory()
        req = rf.get(
            "/x",
            {"range": "custom", "from": first_this.isoformat(), "to": today.isoformat()},
        )
        ctx = employee_access_period_context(self.emp, req)
        self.assertTrue(ctx["fell_back_to_last_month"])
        self.assertEqual(ctx["preset"], "custom")
        self.assertGreaterEqual(ctx["present_days"], 1)

    def test_denied_punches_count_as_attendance(self):
        """AxTrax type 18 (denied) still builds işə gəliş / çıxış like Events UI."""
        day = timezone.localdate() - timedelta(days=2)

        def _at(hour):
            return timezone.make_aware(
                datetime.combine(day, datetime.min.time().replace(hour=hour))
            )

        AccessEvent.objects.create(
            employee=self.emp,
            event_type=AccessEventType.IN,
            result=AccessResult.DENIED,
            occurred_at=_at(9),
            employee_name=self.emp.full_name,
            card_number="006109",
            company_id=self.company.pk,
            company_name=self.company.name,
        )
        AccessEvent.objects.create(
            employee=self.emp,
            event_type=AccessEventType.OUT,
            result=AccessResult.DENIED,
            occurred_at=_at(18),
            employee_name=self.emp.full_name,
            card_number="006109",
            company_id=self.company.pk,
            company_name=self.company.name,
        )
        days = employee_attendance_days(self.emp, day, day)
        self.assertEqual(len(days), 1)
        self.assertTrue(days[0]["has_denied"])
        self.assertEqual(days[0]["status"], "Çıxış")
        self.assertIsNotNone(days[0]["in_at"])
        self.assertIsNotNone(days[0]["out_at"])

    def test_shows_both_cards_and_flags_other(self):
        days = employee_attendance_days(self.emp, self.day_old, self.day_new)
        by_date = {d["date"]: d for d in days}
        self.assertIn(self.day_old, by_date)
        self.assertIn(self.day_new, by_date)
        old = by_date[self.day_old]
        new = by_date[self.day_new]
        self.assertEqual(old["cards"], ["006297"])
        self.assertTrue(old["has_other_card"])
        self.assertEqual(new["cards"], ["006109"])
        self.assertFalse(new["has_other_card"])

    def test_prior_card_owner_not_merged(self):
        days = employee_attendance_days(self.emp, self.day_old, self.day_new)
        # Only emp's punches — not the other person's 006109 punch on day_old as extra person merge
        self.assertEqual(len(days), 2)
        other_days = employee_attendance_days(self.other, self.day_old, self.day_new)
        self.assertEqual(len(other_days), 1)
        self.assertEqual(other_days[0]["cards"], ["006109"])
