from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.residents.models import AccessEvent, AccessEventType, ResidentCompany, ResidentEmployee, ShaftAccessAlert
from apps.residents.shaft_access import (
    create_shaft_alert_from_event,
    detect_shaft_access_after_sync,
    is_shaft_reader,
)

User = get_user_model()


class ShaftReaderMatchTests(TestCase):
    def test_city_point_f_shaft_readers(self):
        self.assertTrue(is_shaft_reader(r"13\Panel 1\F1ShaftElectric"))
        self.assertTrue(is_shaft_reader(r"12\Panel 5\F5ShaftCooling"))
        self.assertTrue(is_shaft_reader(r"24\Panel 7\F7ShaftIT"))
        self.assertTrue(is_shaft_reader("F3ShaftTel"))
        self.assertTrue(is_shaft_reader("f6shaftelectric"))
        self.assertTrue(is_shaft_reader("F2SHAFTCOOLING"))
        self.assertFalse(is_shaft_reader("Shaft1"))
        self.assertFalse(is_shaft_reader("SHAFT_IN"))
        self.assertFalse(is_shaft_reader("F1TurIN"))
        self.assertFalse(is_shaft_reader("BackShaft"))
        self.assertFalse(is_shaft_reader(""))


class ShaftAccessDetectorTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="Shaft Co", slug="shaft-co", portal_active=True, is_internal=False
        )
        self.employee = ResidentEmployee.objects.create(
            company=self.company,
            full_name="Shaft Person",
            card_number="007007",
            is_active=True,
        )
        self.security = User.objects.create_user(
            username="sec-shaft",
            email="sec-shaft@test.az",
            password="Pass12345!",
            role=Role.SECURITY,
        )

    def _event(self, reader_name, **kwargs):
        defaults = {
            "employee": self.employee,
            "event_type": AccessEventType.IN,
            "occurred_at": timezone.now(),
            "employee_name": self.employee.full_name,
            "card_number": self.employee.card_number,
            "reader_name": reader_name,
        }
        defaults.update(kwargs)
        return AccessEvent.objects.create(**defaults)

    def test_creates_alert_for_shaft(self):
        event = self._event(r"13\Panel 1\F1ShaftElectric")
        alert = create_shaft_alert_from_event(event)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.reader_name, r"13\Panel 1\F1ShaftElectric")
        self.assertEqual(alert.card_number, "007007")
        self.assertEqual(alert.company_name, "Shaft Co")
        self.assertTrue(
            User.objects.get(pk=self.security.pk).notifications.filter(is_read=False).exists()
        )

    def test_ignores_non_shaft(self):
        event = self._event("F1TurIN")
        self.assertIsNone(create_shaft_alert_from_event(event))
        self.assertIsNone(create_shaft_alert_from_event(self._event("Shaft1")))

    def test_dedup_same_event(self):
        event = self._event(r"15\Panel 3\F3ShaftIT")
        self.assertIsNotNone(create_shaft_alert_from_event(event))
        self.assertIsNone(create_shaft_alert_from_event(event))
        self.assertEqual(ShaftAccessAlert.objects.count(), 1)

    def test_sync_hook(self):
        e1 = self._event(
            r"3\Panel 4\F4ShaftElectric",
            occurred_at=timezone.now() - timedelta(seconds=10),
        )
        e2 = self._event("F2TurIN", occurred_at=timezone.now())
        created = detect_shaft_access_after_sync([e1, e2])
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].access_event_id, e1.pk)


class ShaftAccessUITests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(
            name="UI Shaft", slug="ui-shaft", portal_active=True, is_internal=False
        )
        self.employee = ResidentEmployee.objects.create(
            company=self.company, full_name="UI Shaft Emp", card_number="008008", is_active=True
        )
        self.security = User.objects.create_user(
            username="sec-shaft-ui",
            email="sec-shaft-ui@test.az",
            password="Pass12345!",
            role=Role.SECURITY,
        )
        event = AccessEvent.objects.create(
            employee=self.employee,
            event_type=AccessEventType.IN,
            occurred_at=timezone.now(),
            employee_name=self.employee.full_name,
            card_number=self.employee.card_number,
            reader_name=r"24\Panel 7\F7ShaftCooling",
        )
        self.alert = ShaftAccessAlert.objects.create(
            employee=self.employee,
            access_event=event,
            employee_name=self.employee.full_name,
            card_number=self.employee.card_number,
            company_id=self.company.pk,
            company_name=self.company.name,
            occurred_at=event.occurred_at,
            event_type=event.event_type,
            reader_name=event.reader_name,
        )
        self.client = Client()

    def test_list_and_detail(self):
        self.client.force_login(self.security)
        listing = self.client.get(reverse("security:alerts_shaft"))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "UI Shaft Emp")
        self.assertContains(listing, "F7ShaftCooling")
        detail = self.client.get(reverse("security:shaft_alert_detail", args=[self.alert.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "008008")
        self.assertContains(detail, "F7ShaftCooling")
        self.assertContains(detail, "Oxuyucu")
        self.alert.refresh_from_db()
        self.assertIsNotNone(self.alert.acknowledged_at)

    def test_acknowledge(self):
        self.client.force_login(self.security)
        resp = self.client.post(reverse("security:shaft_alert_ack", args=[self.alert.pk]))
        self.assertEqual(resp.status_code, 302)
        self.alert.refresh_from_db()
        self.assertIsNotNone(self.alert.acknowledged_at)
