"""Phase 4.1 Scope A — Helpdesk → Facility Work Order lifecycle."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.comms.models import Notification
from apps.core import events as bus
from apps.core.event_handlers import register_default_handlers
from apps.core.services import DomainError
from apps.maintenance.access import can_mutate_work_order, can_view_work_order, work_orders_queryset_for
from apps.maintenance.models import WorkOrderStatus
from apps.maintenance.services import WorkOrderService, create_wo_from_ticket, ticket_has_active_work_order
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.tickets.models import (
    Ticket,
    TicketCategory,
    TicketDepartment,
    TicketPriority,
    TicketStatus,
    TicketSubcategory,
    TicketType,
)
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import create_work_order_from_ticket

User = get_user_model()


class Phase41WorkOrderLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        seed_ticket_taxonomy()
        cls.company = ResidentCompany.objects.create(name="P41 Co", slug="p41-co")
        cls.desk_dept = TicketDepartment.objects.get(code="servicedesk")
        cls.fm_dept = TicketDepartment.objects.get(code="webservis")
        cls.hvac = TicketSubcategory.objects.filter(slug="hvac").first()
        cls.cat = cls.hvac.category if cls.hvac else TicketCategory.objects.filter(is_active=True).first()

    def setUp(self):
        bus.clear_handlers()
        register_default_handlers()
        self.client = Client()
        self.admin = User.objects.create_user(
            username="p41-admin",
            email="p41-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.desk = User.objects.create_user(
            username="p41-desk",
            email="p41-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=self.desk_dept,
        )
        self.fm = User.objects.create_user(
            username="p41-fm",
            email="p41-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=self.fm_dept,
        )
        grant_user_permission(self.fm, "supply.head")
        self.mgmt = User.objects.create_user(
            username="p41-mgmt",
            email="p41-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.assignee = User.objects.create_user(
            username="p41-assignee",
            email="p41-assignee@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=self.desk_dept,
        )

    def tearDown(self):
        bus.clear_handlers()
        register_default_handlers()

    def _ticket(self, *, department=None, status=TicketStatus.IN_PROGRESS, assignee=None, **kwargs):
        defaults = dict(
            code=kwargs.pop("code", f"TK-P41-{Ticket.objects.count() + 1}"),
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.hvac,
            company=self.company,
            description="phase41",
            priority=TicketPriority.NORMAL,
            status=status,
            department=department or self.desk_dept,
            assignee=assignee,
            sla_due_at=timezone.now() + timedelta(hours=8),
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def test_create_wo_does_not_copy_ticket_assignee(self):
        ticket = self._ticket(assignee=self.assignee)
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        self.assertIsNone(wo.assigned_to)
        self.assertEqual(wo.ticket_id, ticket.pk)
        self.assertEqual(wo.status, WorkOrderStatus.OPEN)

    def test_one_active_wo_per_ticket(self):
        ticket = self._ticket(code="TK-P41-UNIQ")
        create_work_order_from_ticket(ticket, actor=self.desk)
        self.assertTrue(ticket_has_active_work_order(ticket))
        with self.assertRaises(DomainError):
            create_work_order_from_ticket(ticket, actor=self.desk)

    def test_wo_created_notifies_supply_operators(self):
        ticket = self._ticket(code="TK-P41-EVT")
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        notes = Notification.objects.filter(user=self.fm, event_key=f"wo.created.{wo.pk}.{self.fm.pk}")
        self.assertEqual(notes.count(), 1)
        # Dedup: re-emit same key must not create another
        bus.emit(
            bus.WORK_ORDER_CREATED,
            payload={"work_order_id": wo.pk, "code": wo.code, "ticket_id": ticket.pk},
            event_key=f"wo.created.{wo.pk}",
        )
        self.assertEqual(notes.count(), 1)

    def test_wo_complete_keeps_ticket_open_never_resolved(self):
        ticket = self._ticket(code="TK-P41-DONE", status=TicketStatus.IN_PROGRESS)
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        WorkOrderService.set_status(wo, WorkOrderStatus.COMPLETED, actor=self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)
        self.assertNotIn(ticket.status, {TicketStatus.RESOLVED, TicketStatus.CLOSED})

    def test_wo_complete_advances_sent_ticket_to_in_progress_only(self):
        ticket = self._ticket(code="TK-P41-SENT", status=TicketStatus.SENT)
        wo = create_wo_from_ticket(ticket)
        WorkOrderService.set_status(wo, WorkOrderStatus.COMPLETED, actor=self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)

    def test_second_wo_allowed_after_first_completed(self):
        ticket = self._ticket(code="TK-P41-REOPEN-WO")
        wo1 = create_work_order_from_ticket(ticket, actor=self.desk)
        WorkOrderService.set_status(wo1, WorkOrderStatus.COMPLETED, actor=self.admin)
        self.assertFalse(ticket_has_active_work_order(ticket))
        wo2 = create_work_order_from_ticket(ticket, actor=self.desk)
        self.assertNotEqual(wo1.pk, wo2.pk)
        self.assertEqual(wo2.status, WorkOrderStatus.OPEN)

    def test_management_can_view_wo_but_not_mutate(self):
        ticket = self._ticket(code="TK-P41-MGMT")
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        self.assertTrue(can_view_work_order(self.mgmt, wo))
        self.assertFalse(can_mutate_work_order(self.mgmt, wo))
        self.assertTrue(work_orders_queryset_for(self.mgmt).filter(pk=wo.pk).exists())

        self.client.force_login(self.mgmt)
        detail = self.client.get(reverse("erp:work_order_detail", kwargs={"code": wo.code}))
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.context["can_mutate_wo"])
        post = self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {"action": "status", "status": WorkOrderStatus.IN_PROGRESS},
        )
        # SoftPermissionDeniedMiddleware → role home (302), not hard 403 body
        self.assertEqual(post.status_code, 302)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrderStatus.OPEN)

    def test_supply_ops_share_inbox_non_supply_denied(self):
        """Facility inbox: supply.head sees/mutates; ordinary desk (other dept) and outsiders do not."""
        sales = User.objects.create_user(
            username="p41-sales",
            email="p41-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        ticket = self._ticket(code="TK-P41-FM", department=self.fm_dept)
        wo = create_work_order_from_ticket(ticket, actor=self.admin)
        self.assertTrue(can_mutate_work_order(self.fm, wo))
        # Ordinary desk (not supply.head, other ticket dept) stays negative.
        self.assertFalse(can_view_work_order(self.desk, wo))
        self.assertFalse(can_mutate_work_order(self.desk, wo))
        self.assertFalse(can_view_work_order(sales, wo))
        self.assertFalse(can_mutate_work_order(sales, wo))

        self.client.force_login(self.fm)
        resp = self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {"action": "status", "status": WorkOrderStatus.IN_PROGRESS},
        )
        self.assertEqual(resp.status_code, 302)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrderStatus.IN_PROGRESS)
