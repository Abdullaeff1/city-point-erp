"""Workflow A follow-up — guest credential identity, employee collision, ambiguity SyncLog."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.integrations.axtrax_health import axtrax_sync_health
from apps.integrations.models import SyncLog, SyncStatus
from apps.reception.models import Guest, GuestVisit, VisitStatus
from apps.reception.services import (
    GUEST_CHECKOUT_AMBIGUOUS_OP,
    checkout_guests_from_access_events,
    create_visitor_access,
    normalize_guest_card,
)
from apps.residents.models import (
    AccessEvent,
    AccessEventType,
    AccessResult,
    ResidentCompany,
    ResidentEmployee,
)


@override_settings(TIME_ZONE="Asia/Baku", USE_TZ=True)
class WorkflowACredentialIdentityTests(TestCase):
    def setUp(self):
        self.co = ResidentCompany.objects.create(
            name="Cred Co", slug="cred-wa", portal_active=True, status="active"
        )

    def _inside_visit(self, *, first="G", last="One", card="007001", held=False):
        guest = Guest.objects.create(first_name=first, last_name=last)
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now() - timedelta(hours=1),
            id_document_held=held,
        )
        access = create_visitor_access(visit, credential=card)
        return visit, access

    def test_A_exact_guest_out_closes_at_event_time(self):
        visit, access = self._inside_visit(card="007001")
        self.assertEqual(access.credential, "007001")
        self.assertEqual(normalize_guest_card("007001"), "007001")
        departed = timezone.now() - timedelta(minutes=3)
        ev = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=departed,
            card_number="007001",
            employee=None,
        )
        self.assertEqual(checkout_guests_from_access_events([ev]), 1)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.LEFT)
        self.assertEqual(visit.check_out_at, departed)

    def test_B_employee_event_same_badge_does_not_close_guest(self):
        visit, _ = self._inside_visit(card="007001")
        emp = ResidentEmployee.objects.create(
            company=self.co,
            full_name="Emp SameBadge",
            card_number="007001",
            is_active=True,
        )
        departed = timezone.now()
        ev = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=departed,
            card_number="007001",  # same normalized display
            employee=emp,
            axtrax_employee_id=4242,
        )
        self.assertEqual(checkout_guests_from_access_events([ev]), 0)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        self.assertIsNone(visit.check_out_at)
        self.assertFalse(
            SyncLog.objects.filter(operation=GUEST_CHECKOUT_AMBIGUOUS_OP).exists()
        )

    def test_C_ambiguous_match_logs_and_keeps_visits_open(self):
        v1, _ = self._inside_visit(first="A1", last="Amb", card="SHARED")
        v2, _ = self._inside_visit(first="A2", last="Amb", card="SHARED")
        occurred = timezone.now()
        ev = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=occurred,
            card_number="SHARED",
        )
        self.assertEqual(checkout_guests_from_access_events([ev]), 0)
        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertEqual(v1.status, VisitStatus.INSIDE)
        self.assertEqual(v2.status, VisitStatus.INSIDE)
        log = SyncLog.objects.get(operation=GUEST_CHECKOUT_AMBIGUOUS_OP)
        self.assertEqual(log.status, SyncStatus.ERROR)
        self.assertEqual(log.correlation_id, f"access_event:{ev.pk}")
        self.assertEqual(log.request_payload["access_event_id"], ev.pk)
        self.assertEqual(log.request_payload["card"], "SHARED")
        self.assertEqual(sorted(log.response_payload["visit_ids"]), sorted([v1.pk, v2.pk]))
        self.assertNotIn("fin", str(log.request_payload).lower())
        health = axtrax_sync_health()
        self.assertIsNotNone(health["last_guest_checkout_ambiguous"])
        self.assertEqual(
            health["last_guest_checkout_ambiguous"]["correlation_id"],
            f"access_event:{ev.pk}",
        )

    def test_D_reprocess_ambiguous_does_not_duplicate_log(self):
        self._inside_visit(first="B1", last="Amb", card="DUP-9")
        self._inside_visit(first="B2", last="Amb", card="DUP-9")
        occurred = timezone.now()
        ev = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=occurred,
            card_number="DUP-9",
        )
        self.assertEqual(checkout_guests_from_access_events([ev]), 0)
        self.assertEqual(checkout_guests_from_access_events([ev, ev]), 0)
        self.assertEqual(
            SyncLog.objects.filter(operation=GUEST_CHECKOUT_AMBIGUOUS_OP).count(),
            1,
        )

    def test_E_distinct_events_same_card_time_use_event_pk(self):
        """AxTrax IdAutoEvents → separate AccessEvent rows; dedupe by PK not card|time."""
        visit, _ = self._inside_visit(card="SAME-T")
        stamp = timezone.now()
        ev1 = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=stamp,
            card_number="SAME-T",
        )
        ev2 = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=stamp,
            card_number="SAME-T",
        )
        self.assertNotEqual(ev1.pk, ev2.pk)
        self.assertEqual(checkout_guests_from_access_events([ev1, ev2]), 1)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.LEFT)
        self.assertEqual(visit.check_out_at, stamp)
        # Second event: visit already closed — no extra checkout, no ambiguity flood
        self.assertEqual(
            SyncLog.objects.filter(operation=GUEST_CHECKOUT_AMBIGUOUS_OP).count(),
            0,
        )

    def test_leading_zero_guest_event_still_matches(self):
        visit, access = self._inside_visit(card="007001")
        self.assertEqual(access.credential, "007001")
        departed = timezone.now()
        ev = AccessEvent.objects.create(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            occurred_at=departed,
            card_number="7001",  # AxTrax may strip zeros; local keys still match
        )
        self.assertEqual(checkout_guests_from_access_events([ev]), 1)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.LEFT)
