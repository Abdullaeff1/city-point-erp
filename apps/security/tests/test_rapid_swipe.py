from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.residents.models import AccessEvent, AccessEventType, RapidCardSwipeAlert, ResidentCompany, ResidentEmployee
from apps.residents.rapid_swipe import (
    detect_rapid_swipes_for_employees,
    find_rapid_windows,
)

User = get_user_model()


class RapidSwipeDetectorTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="Rapid Co", slug="rapid-co", portal_active=True, is_internal=False
        )
        self.employee = ResidentEmployee.objects.create(
            company=self.company,
            full_name="Rapid Person",
            card_number="005001",
            is_active=True,
        )
        self.security = User.objects.create_user(
            username="sec-rapid",
            email="sec-rapid@test.az",
            password="Pass12345!",
            role=Role.SECURITY,
        )
        self.t0 = timezone.now().replace(microsecond=0)

    def _punch(self, offset_sec, event_type=AccessEventType.IN, reader_name="23\\Panel 12\\F1TurIN"):
        return AccessEvent.objects.create(
            employee=self.employee,
            event_type=event_type,
            occurred_at=self.t0 + timedelta(seconds=offset_sec),
            employee_name=self.employee.full_name,
            card_number=self.employee.card_number,
            reader_name=reader_name,
        )

    def test_find_window_requires_three(self):
        events = [self._punch(0), self._punch(10)]
        self.assertEqual(list(find_rapid_windows(events)), [])
        events.append(self._punch(20))
        bursts = list(find_rapid_windows(events))
        self.assertEqual(len(bursts), 1)
        self.assertEqual(len(bursts[0][2]), 3)

    def test_detect_creates_one_alert(self):
        self._punch(0)
        self._punch(15)
        self._punch(30, AccessEventType.OUT)
        alerts = detect_rapid_swipes_for_employees(
            [self.employee.pk], around=self.t0 + timedelta(seconds=40)
        )
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.swipe_count, 3)
        self.assertEqual(alert.card_number, "005001")
        self.assertEqual(alert.company_name, "Rapid Co")
        self.assertEqual(len(alert.swipes), 3)
        self.assertTrue(alert.swipes[0].get("reader_name"))
        self.assertTrue(
            User.objects.get(pk=self.security.pk).notifications.filter(is_read=False).exists()
        )

    def test_two_punches_no_alert(self):
        self._punch(0)
        self._punch(10)
        alerts = detect_rapid_swipes_for_employees(
            [self.employee.pk], around=self.t0 + timedelta(seconds=30)
        )
        self.assertEqual(alerts, [])

    def test_non_f1_readers_ignored(self):
        self._punch(0, reader_name="8\\Panel 13\\F3TurIN")
        self._punch(10, reader_name="8\\Panel 13\\F3TurOUT")
        self._punch(20, reader_name="8\\Panel 13\\F2TurIN")
        alerts = detect_rapid_swipes_for_employees(
            [self.employee.pk], around=self.t0 + timedelta(seconds=40)
        )
        self.assertEqual(alerts, [])

    def test_dedup_second_detect(self):
        self._punch(0)
        self._punch(10)
        self._punch(20)
        first = detect_rapid_swipes_for_employees(
            [self.employee.pk], around=self.t0 + timedelta(seconds=30)
        )
        second = detect_rapid_swipes_for_employees(
            [self.employee.pk], around=self.t0 + timedelta(seconds=30)
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(RapidCardSwipeAlert.objects.count(), 1)


class RapidSwipeSecurityUITests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="UI Co", slug="ui-co", portal_active=True, is_internal=False
        )
        self.employee = ResidentEmployee.objects.create(
            company=self.company, full_name="UI Person", card_number="009009", is_active=True
        )
        self.security = User.objects.create_user(
            username="sec-ui",
            email="sec-ui@test.az",
            password="Pass12345!",
            role=Role.SECURITY,
        )
        self.resident = User.objects.create_user(
            username="res-ui",
            email="res-ui@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        now = timezone.now()
        self.alert = RapidCardSwipeAlert.objects.create(
            employee=self.employee,
            employee_name=self.employee.full_name,
            card_number=self.employee.card_number,
            company_id=self.company.pk,
            company_name=self.company.name,
            window_start=now - timedelta(seconds=40),
            window_end=now,
            swipe_count=3,
            swipes=[
                {
                    "at": (now - timedelta(seconds=40)).isoformat(),
                    "event_type": "in",
                    "access_event_id": 1,
                    "reader_name": "F1TurIN",
                },
                {
                    "at": (now - timedelta(seconds=20)).isoformat(),
                    "event_type": "in",
                    "access_event_id": 2,
                    "reader_name": "F1TurOUT",
                },
                {
                    "at": now.isoformat(),
                    "event_type": "out",
                    "access_event_id": 3,
                    "reader_name": "F1TurBack_IN",
                },
            ],
        )
        self.client = Client()

    def test_resident_forbidden(self):
        self.client.force_login(self.resident)
        self.assertEqual(self.client.get(reverse("security:alerts")).status_code, 403)

    def test_list_and_detail(self):
        self.client.force_login(self.security)
        listing = self.client.get(reverse("security:alerts"))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "UI Person")
        self.assertContains(listing, "009009")
        detail = self.client.get(reverse("security:alert_detail", args=[self.alert.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, self.company.name)
        self.assertContains(detail, "009009")
        self.assertContains(detail, "F1TurIN")

    def test_acknowledge_closes(self):
        self.client.force_login(self.security)
        resp = self.client.post(reverse("security:alert_ack", args=[self.alert.pk]))
        self.assertEqual(resp.status_code, 302)
        self.alert.refresh_from_db()
        self.assertIsNotNone(self.alert.acknowledged_at)
        open_list = self.client.get(reverse("security:alerts") + "?tab=open")
        self.assertNotContains(open_list, "UI Person")
