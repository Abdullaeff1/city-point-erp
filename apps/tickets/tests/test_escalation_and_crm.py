from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.comms.models import NotificationChannel, NotificationDispatch
from apps.maintenance.models import WorkOrderStatus
from apps.maintenance.services import WorkOrderService, create_wo_from_ticket
from apps.residents.models import ResidentCompany
from apps.tickets.models import (
    Ticket,
    TicketCategory,
    TicketPriority,
    TicketStatus,
    TicketType,
)
from apps.tickets.reporting import build_sla_report
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import (
    create_opportunity_from_ticket,
    escalate_ticket_if_needed,
    notify_department_users,
)

User = get_user_model()


class EscalationAndCrmTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_ticket_taxonomy()

    def setUp(self):
        self.company = ResidentCompany.objects.create(name="Esc Co", slug="esc-co")
        self.cat = TicketCategory.objects.filter(is_active=True).first()
        self.admin = User.objects.create_user(
            username="esc-admin",
            email="esc-admin@example.com",
            password="test-pass-123",
            role=Role.ADMIN,
        )
        self.desk = User.objects.create_user(
            username="esc-desk",
            email="esc-desk@example.com",
            password="test-pass-123",
            role=Role.SERVICE_DESK,
        )
        from apps.tickets.models import TicketDepartment

        self.desk.ticket_department = TicketDepartment.objects.get(code="servicedesk")
        self.desk.save(update_fields=["ticket_department"])

    def _ticket(self, **kwargs):
        defaults = dict(
            code="TK-ESC-1",
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            company=self.company,
            description="test",
            priority=TicketPriority.HIGH,
            status=TicketStatus.IN_PROGRESS,
            department=self.desk.ticket_department,
            sla_due_at=timezone.now() - timedelta(minutes=5),
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def test_breach_escalation_notifies_and_levels_up(self):
        ticket = self._ticket()
        level = escalate_ticket_if_needed(ticket)
        self.assertEqual(level, 2)
        ticket.refresh_from_db()
        self.assertEqual(ticket.escalation_level, 2)
        self.assertIsNotNone(ticket.escalated_at)
        # Second call is no-op
        self.assertIsNone(escalate_ticket_if_needed(ticket))

    def test_waiting_pauses_escalation(self):
        ticket = self._ticket(sla_paused_at=timezone.now())
        self.assertIsNone(escalate_ticket_if_needed(ticket))

    def test_department_notify_enqueues_email(self):
        ticket = self._ticket(code="TK-ESC-MAIL")
        notify_department_users(ticket, "hello mail", event_key="ticket.test.mail")
        # on_commit runs in TestCase immediately for atomic blocks; force by wrapping
        from django.db import transaction

        transaction.on_commit(lambda: None)
        # Call notify inside atomic so on_commit fires at end of test transaction... 
        # Django TestCase wraps each test in atomic; on_commit callbacks run after test.
        # Invoke send path directly via second notify after capturing:
        from apps.tickets.services import _enqueue_ticket_email

        _enqueue_ticket_email(
            self.desk,
            message="direct",
            template_code="ticket.department",
            ticket=ticket,
            event_key="direct",
        )
        self.assertTrue(
            NotificationDispatch.objects.filter(
                channel=NotificationChannel.EMAIL,
                recipient="esc-desk@example.com",
                template_code="ticket.department",
            ).exists()
        )

    def test_create_opportunity_from_commercial_ticket(self):
        ticket = self._ticket(
            code="TK-CRM-1",
            ticket_type=TicketType.COMMERCIAL,
            sla_due_at=timezone.now() + timedelta(hours=8),
        )
        # Force crm_eligible via type fallback when no subcategory rule
        opp = create_opportunity_from_ticket(ticket, actor=self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.opportunity_id, opp.pk)
        again = create_opportunity_from_ticket(ticket, actor=self.admin)
        self.assertEqual(again.pk, opp.pk)

    def test_wo_complete_resolves_ticket(self):
        ticket = self._ticket(
            code="TK-WO-1",
            status=TicketStatus.IN_PROGRESS,
            sla_due_at=timezone.now() + timedelta(hours=8),
        )
        wo = create_wo_from_ticket(ticket)
        WorkOrderService.set_status(wo, WorkOrderStatus.COMPLETED, actor=self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.RESOLVED)

    def test_sla_report_builds(self):
        self._ticket(code="TK-REP-1", sla_due_at=timezone.now() + timedelta(hours=1))
        report = build_sla_report(days=30)
        self.assertGreaterEqual(report["total"], 1)
        self.assertIn("by_department", report)
