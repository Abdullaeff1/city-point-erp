from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, TransactionTestCase

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_memberships
from apps.comms.models import NotificationChannel, NotificationDispatch
from apps.comms.services import flush_pending_email_dispatches
from apps.residents.models import ResidentCompany
from apps.tickets.access import can_delete_ticket
from apps.tickets.models import TicketSubcategory
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import (
    create_ticket_from_portal,
    delete_ticket,
    notify_company_users,
)

User = get_user_model()


class MembershipCompanyNotifyTests(TransactionTestCase):
    def setUp(self):
        seed_ticket_taxonomy()
        self.co_a = ResidentCompany.objects.create(
            name="Notify A", slug="notify-a", portal_active=True, is_internal=False
        )
        self.co_b = ResidentCompany.objects.create(
            name="Notify B", slug="notify-b", portal_active=True, is_internal=False
        )
        self.user = User.objects.create_user(
            username="mem-notify",
            email="mem-notify@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        # Primary is A; membership also on B
        ensure_portal_memberships(self.user, [self.co_a, self.co_b], primary_company=self.co_a)
        self.sub = TicketSubcategory.objects.filter(is_active=True).first()

    def test_notify_reaches_secondary_membership(self):
        ticket = create_ticket_from_portal(
            company=self.co_b,
            requester=self.user,
            ticket_type="incident",
            category=self.sub.category,
            subcategory=self.sub,
            description="Secondary company ticket notify",
        )
        before = NotificationDispatch.objects.filter(
            channel=NotificationChannel.EMAIL, template_code="ticket.company"
        ).count()
        notify_company_users(ticket, "Test company notify", event_key=f"m6.notify.{ticket.pk}")
        # on_commit runs in TransactionTestCase
        after = NotificationDispatch.objects.filter(
            channel=NotificationChannel.EMAIL,
            template_code="ticket.company",
            recipient="mem-notify@test.az",
        )
        self.assertGreaterEqual(after.count(), before + 1)
        row = after.order_by("-id").first()
        self.assertIn("subject", row.payload)
        self.assertIn(ticket.code, row.payload.get("subject", ""))


class EmailOutboxFlushTests(TestCase):
    def test_flush_sends_pending_ticket_email(self):
        NotificationDispatch.objects.create(
            channel=NotificationChannel.EMAIL,
            status="pending",
            recipient="outbox@test.az",
            template_code="ticket.department",
            payload={
                "subject": "Ticket TK-1 — şöbə",
                "message": "Hello outbox",
                "ticket_code": "TK-1",
            },
        )
        stats = flush_pending_email_dispatches(template_prefix="ticket.", limit=10)
        self.assertEqual(stats["sent"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["outbox@test.az"])
        self.assertIn("TK-1", mail.outbox[0].subject)
        row = NotificationDispatch.objects.get(recipient="outbox@test.az", template_code="ticket.department")
        self.assertEqual(row.status, "sent")


class PortalDeleteScopeTests(TestCase):
    def setUp(self):
        seed_ticket_taxonomy()
        self.co_a = ResidentCompany.objects.create(
            name="Del A", slug="del-a", portal_active=True, is_internal=False
        )
        self.co_b = ResidentCompany.objects.create(
            name="Del B", slug="del-b", portal_active=True, is_internal=False
        )
        self.user = User.objects.create_user(
            username="del-scope",
            email="del-scope@test.az",
            password="Pass12345!",
            role=Role.RESIDENT_USER,
        )
        ensure_portal_memberships(self.user, [self.co_a, self.co_b], primary_company=self.co_a)
        self.sub = TicketSubcategory.objects.filter(is_active=True).first()
        self.ticket_b = create_ticket_from_portal(
            company=self.co_b,
            requester=self.user,
            ticket_type="incident",
            category=self.sub.category,
            subcategory=self.sub,
            description="Delete scope B",
        )

    def test_delete_allowed_with_membership_even_if_session_narrow(self):
        # Session narrowed to A would deny B; membership alone still allows without company_ids
        self.assertTrue(can_delete_ticket(self.user, self.ticket_b))
        self.assertFalse(can_delete_ticket(self.user, self.ticket_b, company_ids=[self.co_a.pk]))
        self.assertTrue(can_delete_ticket(self.user, self.ticket_b, company_ids=[self.co_b.pk]))
        code = delete_ticket(self.ticket_b, actor=self.user, company_ids=[self.co_b.pk])
        self.assertEqual(code, self.ticket_b.code)
