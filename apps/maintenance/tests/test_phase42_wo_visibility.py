"""Phase 4.2.1 — Facility WO inbox ACL + ticket redaction + orphan coverage."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.maintenance.access import can_mutate_work_order, can_view_work_order, work_orders_queryset_for
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.maintenance.services import next_wo_code
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.tickets.models import (
    Ticket,
    TicketCategory,
    TicketDepartment,
    TicketPriority,
    TicketSubcategory,
    TicketStatus,
    TicketType,
)
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import create_work_order_from_ticket

User = get_user_model()


class Phase42WorkOrderVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        seed_ticket_taxonomy()
        cls.company = ResidentCompany.objects.create(name="P42 Co", slug="p42-co")
        cls.desk_dept = TicketDepartment.objects.get(code="servicedesk")
        cls.fm_dept = TicketDepartment.objects.get(code="webservis")
        cls.hvac = TicketSubcategory.objects.filter(slug="hvac").first()
        cls.cat = cls.hvac.category if cls.hvac else TicketCategory.objects.filter(is_active=True).first()

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="p42-admin",
            email="p42-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.desk = User.objects.create_user(
            username="p42-desk",
            email="p42-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=self.desk_dept,
        )
        self.fm = User.objects.create_user(
            username="p42-fm",
            email="p42-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=self.fm_dept,
        )
        grant_user_permission(self.fm, "supply.head")
        self.mgmt = User.objects.create_user(
            username="p42-mgmt",
            email="p42-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )

    def _ticket(self, *, department=None, code="TK-P42-1", **kwargs):
        defaults = dict(
            code=code,
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.hvac,
            company=self.company,
            description="p42",
            priority=TicketPriority.NORMAL,
            status=TicketStatus.IN_PROGRESS,
            department=department or self.desk_dept,
            sla_due_at=timezone.now() + timedelta(hours=8),
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def test_fm_sees_and_mutates_helpdesk_ticket_wo(self):
        ticket = self._ticket(code="TK-P42-HD", department=self.desk_dept)
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        self.assertTrue(can_view_work_order(self.fm, wo))
        self.assertTrue(can_mutate_work_order(self.fm, wo))
        self.assertTrue(work_orders_queryset_for(self.fm).filter(pk=wo.pk).exists())

        self.client.force_login(self.fm)
        detail = self.client.get(reverse("erp:work_order_detail", kwargs={"code": wo.code}))
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.context["can_mutate_wo"])
        # Ticket dept is Helpdesk — FM must not get a ticket detail link
        self.assertFalse(detail.context["can_view_ticket_link"])
        self.assertContains(detail, "məhdud")
        post = self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {"action": "status", "status": WorkOrderStatus.IN_PROGRESS},
        )
        self.assertEqual(post.status_code, 302)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrderStatus.IN_PROGRESS)

    def test_desk_still_cannot_see_foreign_dept_wo(self):
        ticket = self._ticket(code="TK-P42-FMDEPT", department=self.fm_dept)
        wo = create_work_order_from_ticket(ticket, actor=self.admin)
        self.assertFalse(can_view_work_order(self.desk, wo))
        self.assertFalse(work_orders_queryset_for(self.desk).filter(pk=wo.pk).exists())

    def test_orphan_pm_wo_visible_to_fm_mgmt_not_desk(self):
        orphan = WorkOrder.objects.create(
            code=next_wo_code(),
            title="PM:orphan:test",
            description="orphan",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
            ticket=None,
        )
        self.assertTrue(can_view_work_order(self.fm, orphan))
        self.assertTrue(can_mutate_work_order(self.fm, orphan))
        self.assertTrue(can_view_work_order(self.mgmt, orphan))
        self.assertFalse(can_mutate_work_order(self.mgmt, orphan))
        self.assertFalse(can_view_work_order(self.desk, orphan))
        self.assertTrue(work_orders_queryset_for(self.fm).filter(pk=orphan.pk).exists())
        self.assertFalse(work_orders_queryset_for(self.desk).filter(pk=orphan.pk).exists())

    def test_management_ro_on_facility_inbox_wo(self):
        ticket = self._ticket(code="TK-P42-MGMT-HD", department=self.desk_dept)
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        self.assertTrue(can_view_work_order(self.mgmt, wo))
        self.assertFalse(can_mutate_work_order(self.mgmt, wo))
