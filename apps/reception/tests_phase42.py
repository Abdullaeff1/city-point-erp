"""Phase 4.2.2 — RETURN_PENDING completion + Security RO + notify dedupe."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.comms.models import Notification
from apps.core import events as bus
from apps.core.event_handlers import register_default_handlers
from apps.core.services import DomainError
from apps.reception.models import Guest, GuestVisit, VisitStatus
from apps.reception.services import ReceptionService, checkout_guests_from_access_events
from apps.residents.models import AccessEvent, AccessEventType, AccessResult, ResidentCompany
from apps.rbac.services import seed_rbac_catalog

User = get_user_model()


class Phase42ReceptionSecurityTests(TestCase):
    def setUp(self):
        bus.clear_handlers()
        register_default_handlers()
        seed_rbac_catalog()
        self.client = Client()
        self.company = ResidentCompany.objects.create(name="P42 Rec Co", slug="p42-rec")
        self.reception = User.objects.create_user(
            username="p42-rec",
            email="p42-rec@test.az",
            password="x",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.security = User.objects.create_user(
            username="p42-sec",
            email="p42-sec@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
        )
        self.guest = Guest.objects.create(first_name="Ali", last_name="Test", fin_code="P42FIN01AA")

    def tearDown(self):
        bus.clear_handlers()
        register_default_handlers()

    def _inside_held(self, *, card="CARD-P42"):
        visit = GuestVisit.objects.create(
            guest=self.guest,
            company=self.company,
            status=VisitStatus.INSIDE,
            scheduled_for=timezone.localdate(),
            check_in_at=timezone.now(),
            id_document_held=True,
            created_by=self.reception,
        )
        from apps.reception.services import create_visitor_access

        create_visitor_access(visit, credential=card)
        return visit

    def test_complete_id_return_closes_visit(self):
        visit = self._inside_held()
        pending = ReceptionService.check_out_visit(
            visit, actor=self.reception, id_returned=False, allow_return_pending=True
        )
        self.assertEqual(pending.status, VisitStatus.RETURN_PENDING)
        closed = ReceptionService.complete_id_return(pending, actor=self.reception)
        self.assertEqual(closed.status, VisitStatus.LEFT)
        self.assertFalse(closed.id_document_held)
        self.assertIsNotNone(closed.id_document_returned_at)

    def test_return_pending_notifies_security_and_reception(self):
        visit = self._inside_held(card="CARD-P42-N")
        ReceptionService.check_out_visit(
            visit, actor=self.reception, id_returned=False, allow_return_pending=True
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.security, event_key=f"visitor.return_pending.{visit.pk}.sec.{self.security.pk}"
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.reception, event_key=f"visitor.return_pending.{visit.pk}.rec.{self.reception.pk}"
            ).exists()
        )
        # Dedup
        bus.emit(
            bus.VISITOR_RETURN_PENDING,
            payload={"visit_id": visit.pk, "entity_model": "visit"},
            event_key=f"visitor.return_pending.{visit.pk}",
        )
        self.assertEqual(
            Notification.objects.filter(
                user=self.security, event_key=f"visitor.return_pending.{visit.pk}.sec.{self.security.pk}"
            ).count(),
            1,
        )

    def test_axtrax_out_id_held_then_complete(self):
        visit = self._inside_held(card="CARD-P42-AX")
        event = AccessEvent(
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            card_number="CARD-P42-AX",
            occurred_at=timezone.now(),
        )
        # AxTrax OUT is passage evidence only — does not start RETURN_PENDING.
        n = checkout_guests_from_access_events([event])
        self.assertEqual(n, 0)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.INSIDE)
        ReceptionService.check_out_visit(
            visit, actor=self.reception, id_returned=False, allow_return_pending=True
        )
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.RETURN_PENDING)
        self.assertEqual(checkout_guests_from_access_events([event]), 0)
        ReceptionService.complete_id_return(visit, actor=self.reception)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.LEFT)

    def test_reception_ui_return_id_and_security_ro(self):
        visit = self._inside_held(card="CARD-P42-UI")
        ReceptionService.check_out_visit(
            visit, actor=self.reception, id_returned=False, allow_return_pending=True
        )
        self.client.force_login(self.reception)
        resp = self.client.post(
            reverse("erp:reception_status", args=[visit.pk]),
            {"action": "return_id"},
        )
        self.assertEqual(resp.status_code, 302)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.LEFT)

        self.client.force_login(self.security)
        guests = self.client.get(reverse("security:guests") + "?status=id_pending")
        self.assertEqual(guests.status_code, 200)
        # Security guests journal is GET-only — POST is not a valid mutate path
        post = self.client.post(reverse("security:guests"), {"action": "return_id"})
        self.assertIn(post.status_code, (405, 403, 302))

    def test_complete_id_return_rejects_inside(self):
        visit = self._inside_held(card="CARD-P42-BAD")
        with self.assertRaises(DomainError):
            ReceptionService.complete_id_return(visit, actor=self.reception)
