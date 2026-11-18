from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.invite import send_invite_email
from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.comms.models import NotificationChannel, NotificationDispatch
from apps.comms.services import flush_pending_email_dispatches, requeue_failed_email_dispatches
from apps.core import events as bus
from apps.core.event_handlers import register_default_handlers
from apps.residents.models import ResidentCompany
from apps.tickets.models import Ticket

User = get_user_model()


class OutboxRetryTests(TestCase):
    def test_failed_send_schedules_retry(self):
        row = NotificationDispatch.objects.create(
            channel=NotificationChannel.EMAIL,
            status="pending",
            recipient="retry@test.az",
            template_code="ticket.department",
            payload={"subject": "Retry", "message": "body"},
        )
        with patch("apps.comms.services.send_mail", side_effect=OSError("smtp down")):
            stats = flush_pending_email_dispatches(template_prefix="ticket.", limit=10)
        self.assertEqual(stats["failed"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.attempt_count, 1)
        self.assertIsNotNone(row.next_retry_at)
        self.assertGreater(row.next_retry_at, timezone.now())

    def test_due_retry_then_send(self):
        row = NotificationDispatch.objects.create(
            channel=NotificationChannel.EMAIL,
            status="pending",
            recipient="due@test.az",
            template_code="ticket.company",
            payload={"subject": "Due", "message": "ok"},
            attempt_count=1,
            next_retry_at=timezone.now() - timedelta(minutes=1),
        )
        stats = flush_pending_email_dispatches(template_prefix="ticket.", limit=10)
        self.assertEqual(stats["sent"], 1)
        self.assertGreaterEqual(stats["retried"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "sent")
        self.assertEqual(len(mail.outbox), 1)

    def test_requeue_failed(self):
        row = NotificationDispatch.objects.create(
            channel=NotificationChannel.EMAIL,
            status="failed",
            recipient="requeue@test.az",
            template_code="ticket.escalation",
            payload={"subject": "Requeue", "message": "x"},
            attempt_count=5,
        )
        n = requeue_failed_email_dispatches(template_prefix="ticket.", limit=10)
        self.assertEqual(n, 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")


class OfflineInviteTests(TestCase):
    def setUp(self):
        self.company = ResidentCompany.objects.create(name="Inv Co", slug="inv-co", portal_active=True)
        self.user = User.objects.create_user(
            username="inv-user",
            email="inv@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
            resident_company=self.company,
        )
        ensure_portal_membership(self.user, self.company)

    @override_settings(CP_OFFLINE=True)
    def test_offline_invite_failure_does_not_raise(self):
        with patch("apps.accounts.invite.send_mail", side_effect=OSError("no smtp")):
            row = send_invite_email(user=self.user, absolute_url="https://portal.test/accounts/invite/tok/")
        self.assertEqual(row.status, "failed")
        self.assertIn("https://portal.test/accounts/invite/tok/", (row.payload or {}).get("url", ""))


class DomainEventNotifyTests(TestCase):
    def setUp(self):
        register_default_handlers()
        from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
        from apps.tickets.models import TicketSubcategory

        seed_ticket_taxonomy()
        self.assignee = User.objects.create_user(
            username="evt-assignee",
            email="assignee@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
        )
        self.company = ResidentCompany.objects.create(name="Evt Co", slug="evt-co", portal_active=True)
        self.sub = TicketSubcategory.objects.filter(is_active=True).first()

    def test_ticket_assigned_event_creates_in_app(self):
        from apps.comms.models import Notification

        ticket = Ticket.objects.create(
            code="TK-M9-1",
            company=self.company,
            description="event notify",
            assignee=self.assignee,
            category=self.sub.category,
            subcategory=self.sub,
            status="open",
        )
        bus.emit(
            bus.TICKET_ASSIGNED,
            payload={"ticket_id": ticket.pk, "entity_model": "ticket"},
        )
        note = Notification.objects.filter(
            user=self.assignee, event_key=f"ticket.assigned.{ticket.pk}.{self.assignee.pk}"
        ).first()
        self.assertIsNotNone(note)
        self.assertIn(ticket.code, note.message)
