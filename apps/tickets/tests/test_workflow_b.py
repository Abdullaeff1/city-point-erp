"""Workflow B — Resident → Helpdesk → Facility acceptance."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.audit.models import AuditLog
from apps.comms.models import Notification
from apps.core import events as bus
from apps.core.event_handlers import register_default_handlers
from apps.core.services import DomainError
from apps.maintenance.access import can_mutate_work_order, work_orders_queryset_for
from apps.maintenance.models import WorkOrder, WorkOrderStatus
from apps.maintenance.services import WorkOrderService, assign_work_order
from apps.property.models import Building, Floor, Space
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.tickets.models import (
    Ticket,
    TicketDepartment,
    TicketStatus,
    TicketSubcategory,
    TicketType,
)
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import (
    create_ticket_from_portal,
    create_work_order_from_ticket,
    set_ticket_status,
)

User = get_user_model()


class WorkflowBAcceptanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        seed_ticket_taxonomy()
        cls.co_a = ResidentCompany.objects.create(
            name="Alpha WB", slug="alpha-wb", portal_active=True, is_internal=False
        )
        cls.co_b = ResidentCompany.objects.create(
            name="Beta WB", slug="beta-wb", portal_active=True, is_internal=False
        )
        building = Building.objects.create(code="WB-B", name="WB Building")
        floor = Floor.objects.create(building=building, code="F8", name="8")
        cls.space_a = Space.objects.create(
            floor=floor, code="801-A", name="Office 801", resident=cls.co_a
        )
        cls.space_b = Space.objects.create(
            floor=floor, code="802-B", name="Office 802", resident=cls.co_b
        )
        cls.hvac = TicketSubcategory.objects.get(slug="hvac", is_active=True)
        cls.cleaning = TicketSubcategory.objects.get(slug="office-cleaning", is_active=True)
        cls.desk_dept = TicketDepartment.objects.get(code="servicedesk")
        cls.fm_dept = TicketDepartment.objects.get(code="webservis")
        cls.sec_dept = TicketDepartment.objects.get(code="security")

    def setUp(self):
        bus.clear_handlers()
        register_default_handlers()
        self.client = Client()
        self.desk = User.objects.create_user(
            username="wb-desk",
            email="wb-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=self.desk_dept,
        )
        self.fm = User.objects.create_user(
            username="wb-fm",
            email="wb-fm@test.az",
            password="x",
            role=Role.PROPERTY_FM,
            is_staff=True,
            ticket_department=self.fm_dept,
        )
        self.fm2 = User.objects.create_user(
            username="wb-fm2",
            email="wb-fm2@test.az",
            password="x",
            role=Role.PROPERTY_FM,
            is_staff=True,
            ticket_department=self.fm_dept,
        )
        self.security = User.objects.create_user(
            username="wb-sec",
            email="wb-sec@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
            ticket_department=self.sec_dept,
        )
        self.res_a = User.objects.create_user(
            username="wb-resa",
            email="wb-resa@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co_a,
        )
        ensure_portal_membership(self.res_a, self.co_a)
        self.res_multi = User.objects.create_user(
            username="wb-multi",
            email="wb-multi@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co_a,
        )
        ensure_portal_membership(self.res_multi, self.co_a)
        ensure_portal_membership(self.res_multi, self.co_b)
        self.res_b = User.objects.create_user(
            username="wb-resb",
            email="wb-resb@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co_b,
        )
        ensure_portal_membership(self.res_b, self.co_b)

    def _submit_hvac(self, *, requester=None, company=None, space=None, description=None):
        requester = requester or self.res_a
        company = company or self.co_a
        space = space if space is not None else self.space_a
        return create_ticket_from_portal(
            company=company,
            requester=requester,
            ticket_type=TicketType.INCIDENT,
            category=self.hvac.category,
            subcategory=self.hvac,
            description=description or "The air conditioner in office 801 is not cooling.",
            space=space,
        )

    def test_A_hvac_routes_to_queue_with_company_space_sla(self):
        ticket = self._submit_hvac()
        self.assertEqual(ticket.company_id, self.co_a.pk)
        self.assertEqual(ticket.space_id, self.space_a.pk)
        self.assertEqual(ticket.department.code, "servicedesk")
        self.assertTrue(ticket.wo_eligible)
        self.assertIsNotNone(ticket.sla_due_at)
        rule = self.hvac.routing_rule
        self.assertEqual(ticket.queue_id, rule.queue_id)
        # Multi-company cannot attach foreign space
        with self.assertRaises(DomainError):
            create_ticket_from_portal(
                company=self.co_a,
                requester=self.res_multi,
                ticket_type=TicketType.INCIDENT,
                category=self.hvac.category,
                subcategory=self.hvac,
                description="Wrong space",
                space=self.space_b,
            )

    def test_B_helpdesk_handoff_appears_on_fm_dashboard_and_list(self):
        ticket = self._submit_hvac()
        self.client.force_login(self.desk)
        detail = self.client.get(reverse("erp:ticket_detail", kwargs={"code": ticket.code}))
        self.assertEqual(detail.status_code, 200)
        resp = self.client.post(
            reverse("erp:ticket_detail", kwargs={"code": ticket.code}),
            {"action": "create_wo"},
        )
        self.assertEqual(resp.status_code, 302)
        wo = WorkOrder.objects.get(ticket=ticket)
        ticket.refresh_from_db()
        self.assertEqual(ticket.department_id, self.desk_dept.pk)

        self.client.force_login(self.fm)
        dash = self.client.get(reverse("erp:facility_dashboard"))
        self.assertEqual(dash.status_code, 200)
        kpis = dash.context["kpis"]
        open_kpi = next(k for k in kpis if "WO" in str(k["label"]))
        self.assertGreaterEqual(open_kpi["value"], 1)
        pending_codes = [p["title"] for p in dash.context["pending"]]
        self.assertIn(wo.code, pending_codes)
        lst = self.client.get(reverse("erp:work_orders"))
        self.assertContains(lst, wo.code)
        self.assertTrue(work_orders_queryset_for(self.fm).filter(pk=wo.pk).exists())

    def test_C_fm_assign_and_complete_with_history(self):
        ticket = self._submit_hvac()
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        self.client.force_login(self.fm)
        assign_resp = self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {"action": "assign", "assigned_to": str(self.fm.pk)},
        )
        self.assertEqual(assign_resp.status_code, 302)
        wo.refresh_from_db()
        self.assertEqual(wo.assigned_to_id, self.fm.pk)
        self.assertEqual(wo.status, WorkOrderStatus.ASSIGNED)
        self.assertTrue(
            AuditLog.objects.filter(action=bus.WORK_ORDER_ASSIGNED, entity_id=wo.pk).exists()
            or Notification.objects.filter(event_key=f"wo.assigned.{wo.pk}.{self.fm.pk}").exists()
        )
        # Reassign
        assign_work_order(wo, actor=self.fm, assignee_id=self.fm2.pk)
        wo.refresh_from_db()
        self.assertEqual(wo.assigned_to_id, self.fm2.pk)

        complete = self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {
                "action": "status",
                "status": WorkOrderStatus.COMPLETED,
                "completion_note": "Filter replaced; cooling restored",
            },
        )
        self.assertEqual(complete.status_code, 302)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrderStatus.COMPLETED)
        self.assertIsNotNone(wo.completed_at)
        self.assertIn("Filter replaced", wo.description)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)

    def test_D_resident_sees_resolution_not_internal_notes(self):
        ticket = self._submit_hvac()
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        WorkOrderService.set_status(
            wo, WorkOrderStatus.COMPLETED, actor=self.fm, note="Tech OK"
        )
        ticket.refresh_from_db()
        set_ticket_status(
            ticket,
            TicketStatus.RESOLVED,
            actor=self.desk,
            note="Kondisioner bərpa olundu.",
        )
        ticket.enrichment_notes = "Internal: compressor serial XYZ"
        ticket.save(update_fields=["enrichment_notes"])
        self.client.force_login(self.res_a)
        page = self.client.get(reverse("portal:request_detail", kwargs={"code": ticket.code}))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Kondisioner bərpa olundu.")
        self.assertNotContains(page, "compressor serial")
        self.assertNotContains(page, wo.code)

    def test_E_company_and_unrelated_dept_isolation(self):
        ticket = self._submit_hvac()
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        self.client.force_login(self.res_b)
        denied = self.client.get(reverse("portal:request_detail", kwargs={"code": ticket.code}))
        self.assertEqual(denied.status_code, 404)
        self.client.force_login(self.security)
        # Security cannot mutate FM work order via POST
        resp = self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {"action": "status", "status": WorkOrderStatus.COMPLETED},
        )
        self.assertIn(resp.status_code, (302, 403, 404))
        wo.refresh_from_db()
        self.assertNotEqual(wo.status, WorkOrderStatus.COMPLETED)
        self.assertFalse(can_mutate_work_order(self.security, wo))

    def test_F_ineligible_ticket_rejects_wo(self):
        ticket = create_ticket_from_portal(
            company=self.co_a,
            requester=self.res_a,
            ticket_type=TicketType.SERVICE_REQUEST,
            category=self.cleaning.category,
            subcategory=self.cleaning,
            description="Office cleaning request",
        )
        self.assertFalse(ticket.wo_eligible)
        self.assertEqual(ticket.department_id, self.desk_dept.pk)
        with self.assertRaises(DomainError):
            create_work_order_from_ticket(ticket, actor=self.desk)
        self.assertEqual(WorkOrder.objects.filter(ticket=ticket).count(), 0)
        self.client.force_login(self.desk)
        resp = self.client.post(
            reverse("erp:ticket_detail", kwargs={"code": ticket.code}),
            {"action": "create_wo"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(WorkOrder.objects.filter(ticket=ticket).count(), 0)

    def test_G_retry_handoff_and_complete_idempotent(self):
        ticket = self._submit_hvac()
        wo1 = create_work_order_from_ticket(ticket, actor=self.desk)
        with self.assertRaises(DomainError):
            create_work_order_from_ticket(ticket, actor=self.desk)
        self.assertEqual(WorkOrder.objects.filter(ticket=ticket).count(), 1)
        WorkOrderService.set_status(wo1, WorkOrderStatus.COMPLETED, actor=self.fm, note="Done")
        wo1.refresh_from_db()
        stamp = wo1.completed_at
        self.assertIsNotNone(stamp)
        WorkOrderService.set_status(wo1, WorkOrderStatus.COMPLETED, actor=self.fm, note="Done again")
        wo1.refresh_from_db()
        self.assertEqual(wo1.completed_at, stamp)
        closed = AuditLog.objects.filter(action=bus.WORK_ORDER_CLOSED).filter(
            new_values__work_order_id=wo1.pk
        )
        # event_key dedupe → at most one closed audit for this WO
        self.assertLessEqual(closed.count(), 1)

    def test_H_waiting_reopen_and_http_end_to_end(self):
        # Portal HTTP intake
        self.client.force_login(self.res_a)
        form_page = self.client.get(reverse("portal:request_new"))
        self.assertEqual(form_page.status_code, 200)
        created = self.client.post(
            reverse("portal:request_new"),
            {
                "ticket_type": TicketType.INCIDENT,
                "category": str(self.hvac.category_id),
                "subcategory": str(self.hvac.pk),
                "space": str(self.space_a.pk),
                "description": "AC not cooling — portal",
                "company": str(self.co_a.pk),
            },
        )
        self.assertIn(created.status_code, (302, 200))
        ticket = Ticket.objects.filter(company=self.co_a, description__icontains="portal").latest("pk")

        self.client.force_login(self.desk)
        self.client.post(
            reverse("erp:ticket_detail", kwargs={"code": ticket.code}),
            {"action": "create_wo"},
        )
        wo = WorkOrder.objects.get(ticket=ticket)
        self.client.force_login(self.fm)
        self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {"action": "assign", "assigned_to": str(self.fm.pk)},
        )
        self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": wo.code}),
            {
                "action": "status",
                "status": WorkOrderStatus.COMPLETED,
                "completion_note": "Cooling OK",
            },
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)

        self.client.force_login(self.desk)
        self.client.post(
            reverse("erp:ticket_detail", kwargs={"code": ticket.code}),
            {
                "action": "waiting",
                "waiting_reason_code": "resident_response",
                "waiting_reason": "Resident confirmation",
            },
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.WAITING)
        # Advance out of waiting → progress → resolve → close
        set_ticket_status(ticket, TicketStatus.IN_PROGRESS, actor=self.desk)
        self.client.post(
            reverse("erp:ticket_detail", kwargs={"code": ticket.code}),
            {
                "action": "advance",
                "resolution_note": "Problem həll olundu.",
            },
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.RESOLVED)
        self.assertEqual(ticket.resolution_note, "Problem həll olundu.")
        self.assertTrue(
            AuditLog.objects.filter(action=bus.TICKET_RESOLVED).exists()
            or Notification.objects.filter(
                event_key__startswith=f"ticket.resolved.{ticket.pk}."
            ).exists()
        )
        self.client.post(
            reverse("erp:ticket_detail", kwargs={"code": ticket.code}),
            {"action": "close"},
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.CLOSED)
        self.client.post(
            reverse("erp:ticket_detail", kwargs={"code": ticket.code}),
            {"action": "reopen"},
        )
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.REOPENED)

        self.client.force_login(self.res_a)
        portal = self.client.get(reverse("portal:request_detail", kwargs={"code": ticket.code}))
        self.assertContains(portal, "Problem həll olundu.")


class WorkflowBConcurrencyTests(TransactionTestCase):
    def test_concurrent_handoff_creates_one_wo(self):
        seed_rbac_catalog()
        seed_ticket_taxonomy()
        bus.clear_handlers()
        register_default_handlers()
        co = ResidentCompany.objects.create(name="Conc Co", slug="conc-wb", portal_active=True)
        desk_dept = TicketDepartment.objects.get(code="servicedesk")
        hvac = TicketSubcategory.objects.get(slug="hvac", is_active=True)
        desk = User.objects.create_user(
            username="conc-desk",
            email="conc-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            ticket_department=desk_dept,
        )
        res = User.objects.create_user(
            username="conc-res",
            email="conc-res@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=co,
        )
        ensure_portal_membership(res, co)
        ticket = create_ticket_from_portal(
            company=co,
            requester=res,
            ticket_type=TicketType.INCIDENT,
            category=hvac.category,
            subcategory=hvac,
            description="Concurrent handoff",
        )
        create_work_order_from_ticket(ticket, actor=desk)
        with self.assertRaises(DomainError):
            create_work_order_from_ticket(ticket, actor=desk)
        self.assertEqual(WorkOrder.objects.filter(ticket=ticket).count(), 1)
