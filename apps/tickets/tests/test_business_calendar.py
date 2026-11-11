from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.tickets.business_calendar import (
    add_business_hours,
    is_fixed_holiday,
    is_workday,
    next_open,
)

BAKU = ZoneInfo("Asia/Baku")


@override_settings(TIME_ZONE="Asia/Baku", USE_TZ=True)
class BusinessCalendarTests(SimpleTestCase):
    def test_novruz_and_sunday_off(self):
        self.assertTrue(is_fixed_holiday(datetime(2026, 3, 21).date()))
        self.assertFalse(is_workday(datetime(2026, 3, 21).date()))  # Novruz Sat
        self.assertFalse(is_workday(datetime(2026, 11, 15).date()))  # Sunday
        self.assertTrue(is_workday(datetime(2026, 11, 14).date()))  # Saturday

    def test_next_open_skips_night_to_morning(self):
        friday_evening = timezone.make_aware(datetime(2026, 11, 13, 19, 0), BAKU)
        opened = next_open(friday_evening)
        self.assertEqual(opened.astimezone(BAKU).strftime("%Y-%m-%d %H:%M"), "2026-11-14 09:00")

    def test_add_4_business_hours_same_day(self):
        start = timezone.make_aware(datetime(2026, 11, 10, 10, 0), BAKU)  # Tuesday
        due = add_business_hours(start, 4)
        self.assertEqual(due.astimezone(BAKU).strftime("%Y-%m-%d %H:%M"), "2026-11-10 14:00")

    def test_add_hours_spans_overnight_and_sunday(self):
        # Saturday 16:00 + 4h → 2h Sat + 2h Mon = Monday 11:00
        start = timezone.make_aware(datetime(2026, 11, 14, 16, 0), BAKU)
        due = add_business_hours(start, 4)
        self.assertEqual(due.astimezone(BAKU).strftime("%Y-%m-%d %H:%M"), "2026-11-16 11:00")

    def test_add_hours_skips_novruz(self):
        # 19 Mar 2026 is Thursday before Novruz 20–24; +9h should land after holidays
        start = timezone.make_aware(datetime(2026, 3, 19, 10, 0), BAKU)
        due = add_business_hours(start, 9)
        # 8h left same day → 18:00; 1h → next workday after Novruz
        # 20–24 Mar holiday; 25 Mar Wed 09:00 + 1h = 10:00
        self.assertEqual(due.astimezone(BAKU).strftime("%Y-%m-%d %H:%M"), "2026-03-25 10:00")
