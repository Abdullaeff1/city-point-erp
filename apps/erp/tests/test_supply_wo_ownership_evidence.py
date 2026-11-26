"""Cross-department WO ownership — demonstrate evidence, do not invent handoff fields."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.maintenance.access import can_mutate_work_order, can_view_work_order
from apps.maintenance.models import WorkOrder, WorkOrderStatus
from apps.maintenance.services import next_wo_code
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


class SupplyWorkOrderOwnershipEvidenceTests(TestCase):
    """Persisted evidence today: ticket.department, WO.assigned_to; no handoff table."""

    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        seed_ticket_taxonomy()
        cls.company = ResidentCompany.objects.create(name="Own Co", slug="own-co")
        cls.desk_dept = TicketDepartment.objects.get(code="servicedesk")
        cls.sec_dept = TicketDepartment.objects.get(code="security")
        hvac = TicketSubcategory.objects.filter(slug="hvac").first()
        cls.cat = hvac.category if hvac else TicketCategory.objects.filter(is_active=True).first()
        cls.sub = hvac
        cls.desk = User.objects.create_user(
            username="own-desk",
            email="own-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=cls.desk_dept,
        )
        cls.head = User.objects.create_user(
            username="own-head",
            email="own-head@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(cls.head, "supply.head")
        cls.admin = User.objects.create_user(
            username="own-admin",
            email="own-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )

    def _ticket(self, *, code, department):
        return Ticket.objects.create(
            code=code,
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.sub,
            company=self.company,
            description="ownership",
            priority=TicketPriority.NORMAL,
            status=TicketStatus.IN_PROGRESS,
            department=department,
            sla_due_at=timezone.now() + timedelta(hours=4),
        )

    def test_matrix_security_handoff_assign_orphan(self):
        security = self._ticket(code="TK-OWN-SEC", department=self.sec_dept)
        wo_sec = create_work_order_from_ticket(security, actor=self.admin)

        # Explicit handoff evidence = department reassignment onto Supply taxonomy.
        handed = self._ticket(code="TK-OWN-HO", department=self.sec_dept)
        handed.department = self.desk_dept
        handed.save(update_fields=["department"])
        wo_hand = create_work_order_from_ticket(handed, actor=self.admin)

        assigned_ticket = self._ticket(code="TK-OWN-ASG", department=self.sec_dept)
        wo_asg = create_work_order_from_ticket(assigned_ticket, actor=self.admin)
        wo_asg.assigned_to = self.desk
        wo_asg.status = WorkOrderStatus.ASSIGNED
        wo_asg.save(update_fields=["assigned_to", "status"])

        orphan = WorkOrder.objects.create(
            code=next_wo_code(),
            title="historical no owner",
            status=WorkOrderStatus.OPEN,
            ticket=None,
        )

        # Ordinary (bound to servicedesk): Security foreign blocked; handoff via dept; assign; orphan no
        self.assertFalse(can_view_work_order(self.desk, wo_sec))
        self.assertFalse(can_mutate_work_order(self.desk, wo_sec))
        self.assertTrue(can_view_work_order(self.desk, wo_hand))
        self.assertTrue(can_mutate_work_order(self.desk, wo_hand))
        self.assertEqual(wo_hand.ticket.department_id, self.desk_dept.pk)
        self.assertTrue(can_view_work_order(self.desk, wo_asg))
        self.assertTrue(can_mutate_work_order(self.desk, wo_asg))
        self.assertEqual(wo_asg.assigned_to_id, self.desk.pk)
        self.assertFalse(can_view_work_order(self.desk, orphan))
        self.assertFalse(can_mutate_work_order(self.desk, orphan))

        # Head facility inbox: sees Security + orphan; can mutate both (current product)
        self.assertTrue(can_view_work_order(self.head, wo_sec))
        self.assertTrue(can_mutate_work_order(self.head, wo_sec))
        self.assertTrue(can_view_work_order(self.head, wo_hand))
        self.assertTrue(can_mutate_work_order(self.head, wo_hand))
        self.assertTrue(can_view_work_order(self.head, wo_asg))
        self.assertTrue(can_mutate_work_order(self.head, wo_asg))
        self.assertTrue(can_view_work_order(self.head, orphan))
        self.assertTrue(can_mutate_work_order(self.head, orphan))

        # Documented gap: no persisted handoff actor/timestamp — only department FK / assignee.
        self.assertFalse(hasattr(wo_sec, "handed_to_department_id"))
        self.assertFalse(hasattr(wo_sec, "handoff_at"))
