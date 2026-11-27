"""Köhnə əməkdaş kart backfill — AccessEvent tarixçəsindən."""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from apps.residents.former_cards import backfill_former_employee_cards, infer_card_from_events
from apps.residents.models import (
    AccessEvent,
    AccessEventType,
    AccessResult,
    ResidentCompany,
    ResidentEmployee,
)


class FormerCardBackfillTests(TestCase):
    def setUp(self):
        self.co = ResidentCompany.objects.create(
            name="Backfill Co", slug="backfill-co", is_internal=False
        )
        self.emp = ResidentEmployee.objects.create(
            company=self.co,
            full_name="Köhnə İşçi",
            card_number="",
            is_active=False,
            deactivated_at=timezone.now(),
        )
        AccessEvent.objects.create(
            employee=self.emp,
            employee_name=self.emp.full_name,
            company_id=self.co.pk,
            company_name=self.co.name,
            event_type=AccessEventType.IN,
            result=AccessResult.GRANTED,
            occurred_at=timezone.now(),
            card_number="006001",
            reader_name="F1TurIN",
        )
        AccessEvent.objects.create(
            employee=self.emp,
            employee_name=self.emp.full_name,
            company_id=self.co.pk,
            company_name=self.co.name,
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=timezone.now(),
            card_number="006001",
            reader_name="F1TurBack_OUT",
        )
        # Empty snapshot event — should be filled on apply
        AccessEvent.objects.create(
            employee=self.emp,
            employee_name=self.emp.full_name,
            company_id=self.co.pk,
            company_name=self.co.name,
            event_type=AccessEventType.IN,
            result=AccessResult.GRANTED,
            occurred_at=timezone.now(),
            card_number="",
            reader_name="F1TurIN",
        )

    def test_infer_and_apply_backfill(self):
        self.assertEqual(infer_card_from_events(self.emp.pk), "006001")
        dry = backfill_former_employee_cards(apply=False)
        self.assertEqual(dry["inferred"], 1)
        self.assertEqual(dry["employees_would_update"], 1)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.card_number, "")

        applied = backfill_former_employee_cards(apply=True)
        self.assertEqual(applied["employees_updated"], 1)
        self.assertGreaterEqual(applied["events_updated"], 1)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.card_number, "006001")
        self.assertEqual(
            AccessEvent.objects.filter(employee=self.emp, card_number="").count(),
            0,
        )
        # Idempotent
        again = backfill_former_employee_cards(apply=True)
        self.assertEqual(again["employees_updated"], 0)
        self.assertEqual(again["skipped_already_set"], 1)
