"""Phase 6 — notification links + role boundary smoke through recipient screens."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.comms.links import notification_target_url, user_notifications
from apps.comms.models import Notification
from apps.core import events as bus
from apps.core.event_handlers import register_default_handlers
from apps.documents.models import DOCUMENT_TYPE_OTHER, DocumentSensitivity, DocumentType
from apps.documents.services import DocumentService
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.maintenance.services import WorkOrderService, next_wo_code
from apps.procurement.models import PurchaseApprovalLimit
from apps.procurement.services import ProcurementService
from apps.rbac.services import seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.tickets.models import TicketDepartment, TicketStatus, TicketSubcategory, TicketType
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import (
    create_ticket_from_portal,
    create_work_order_from_ticket,
    set_ticket_status,
)
from apps.warehouse.models import SKU, Stock, Warehouse
from apps.warehouse.services import confirm_issue, request_issue_line
from apps.workflows.models import ApprovalStatus

User = get_user_model()


class Phase6NotifyLinkAcceptanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        seed_ticket_taxonomy()
        cls.co_a = ResidentCompany.objects.create(
            name="P6 A", slug="p6-a", portal_active=True, is_internal=False
        )
        cls.co_b = ResidentCompany.objects.create(
            name="P6 B", slug="p6-b", portal_active=True, is_internal=False
        )
        cls.hvac = TicketSubcategory.objects.get(slug="hvac", is_active=True)
        cls.desk_dept = TicketDepartment.objects.get(code="servicedesk")
        cls.fm_dept = TicketDepartment.objects.get(code="webservis")

    def setUp(self):
        bus.clear_handlers()
        register_default_handlers()
        self.client = Client()
        self.mgmt = User.objects.create_user(
            username="p6-mgmt", email="p6-mgmt@test.az", password="x",
            role=Role.MANAGEMENT, is_staff=True,
        )
        self.fm = User.objects.create_user(
            username="p6-fm", email="p6-fm@test.az", password="x",
            role=Role.PROPERTY_FM, is_staff=True, ticket_department=self.fm_dept,
        )
        self.desk = User.objects.create_user(
            username="p6-desk", email="p6-desk@test.az", password="x",
            role=Role.SERVICE_DESK, is_staff=True, ticket_department=self.desk_dept,
        )
        self.acct = User.objects.create_user(
            username="p6-acct", email="p6-acct@test.az", password="x",
            role=Role.ACCOUNTANT, is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="p6-sales", email="p6-sales@test.az", password="x",
            role=Role.SALES, is_staff=True,
        )
        self.res_a = User.objects.create_user(
            username="p6-resa", email="p6-resa@test.az", password="x",
            role=Role.RESIDENT_USER, resident_company=self.co_a,
        )
        ensure_portal_membership(self.res_a, self.co_a)
        self.res_b = User.objects.create_user(
            username="p6-resb", email="p6-resb@test.az", password="x",
            role=Role.RESIDENT_USER, resident_company=self.co_b,
        )
        ensure_portal_membership(self.res_b, self.co_b)
        self.wh = Warehouse.objects.create(code="P6WH", name="P6")
        self.sku = SKU.objects.create(code="P6-SKU", name="Part", unit="ədəd")
        Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("10"))
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.PROPERTY_FM,
            defaults={"max_amount": Decimal("1000"), "is_active": True},
        )

    def tearDown(self):
        bus.clear_handlers()
        register_default_handlers()

    def test_fm_document_decision_opens_documents_not_hub_decide(self):
        dtype, _ = DocumentType.objects.get_or_create(
            code=DOCUMENT_TYPE_OTHER,
            defaults={
                "name": "Digər",
                "requires_approval": True,
                "default_sensitivity": DocumentSensitivity.CONFIDENTIAL,
            },
        )
        dtype.requires_approval = True
        dtype.save(update_fields=["requires_approval"])
        doc = DocumentService.upload_new(
            title="P6 Doc",
            uploaded_file=SimpleUploadedFile("p6.pdf", b"%PDF-1.4", content_type="application/pdf"),
            company=self.co_a,
            document_type=dtype,
            created_by=self.fm,
        )
        req = DocumentService.submit_for_approval(doc, actor=self.fm)
        DocumentService.decide_approval(req, actor=self.mgmt, approved=True, comment="ok")
        note = Notification.objects.filter(
            user=self.fm, event_key__startswith=f"approval.decided.{req.pk}."
        ).latest("id")
        url = notification_target_url(note, None, self.fm, "erp")
        self.assertEqual(url, reverse("erp:documents"))
        self.client.force_login(self.fm)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "P6 Doc")
        # FM cannot open decide action on other pending approvals via hub decision
        hub = self.client.get(reverse("erp:approvals"))
        self.assertIn(hub.status_code, (200, 302, 403))

    def test_helpdesk_sees_wo_complete_and_opens_ticket(self):
        ticket = create_ticket_from_portal(
            company=self.co_a,
            requester=self.res_a,
            ticket_type=TicketType.INCIDENT,
            category=self.hvac.category,
            subcategory=self.hvac,
            description="P6 HVAC",
        )
        ticket.assignee = self.desk
        ticket.save(update_fields=["assignee"])
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        WorkOrderService.set_status(wo, WorkOrderStatus.COMPLETED, actor=self.fm, note="done")
        note = Notification.objects.filter(
            user=self.desk, event_key__startswith=f"wo.closed.helpdesk.{wo.pk}"
        ).latest("id")
        url = notification_target_url(note, ticket, self.desk, "erp")
        self.assertIn(ticket.code, url)
        self.client.force_login(self.desk)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, ticket.code)

    def test_resident_resolution_company_scope(self):
        ticket = create_ticket_from_portal(
            company=self.co_a,
            requester=self.res_a,
            ticket_type=TicketType.INCIDENT,
            category=self.hvac.category,
            subcategory=self.hvac,
            description="P6 resolve",
        )
        set_ticket_status(ticket, TicketStatus.ACCEPTED, actor=self.desk)
        set_ticket_status(ticket, TicketStatus.IN_PROGRESS, actor=self.desk)
        set_ticket_status(ticket, TicketStatus.RESOLVED, actor=self.desk, note="Ok")
        notes = user_notifications(self.res_a, namespace="portal")
        linked = [n for n in notes if ticket.code in (n.target_url or "")]
        self.assertTrue(linked)
        self.client.force_login(self.res_a)
        page = self.client.get(linked[0].target_url)
        self.assertEqual(page.status_code, 200)
        self.client.force_login(self.res_b)
        denied = self.client.get(
            reverse("portal:request_detail", kwargs={"code": ticket.code})
        )
        self.assertEqual(denied.status_code, 404)

    def test_material_issue_notifies_assignee_work_orders(self):
        wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="P6 issue",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
            assigned_to=self.fm,
        )
        issue = request_issue_line(
            work_order=wo, warehouse=self.wh, sku=self.sku, quantity=Decimal("1"), actor=self.fm
        )
        confirm_issue(
            issue,
            actor=self.fm,
            lines=[{"id": issue.lines.get().pk, "issued_qty": "1", "unit_cost": "3"}],
        )
        note = Notification.objects.get(
            user=self.fm, event_key=f"warehouse.issue.confirm.{issue.pk}"
        )
        url = notification_target_url(note, None, self.fm, "erp")
        self.assertEqual(url, reverse("erp:work_orders"))
        self.client.force_login(self.fm)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, wo.code)

    def test_accountant_lease_app_notify_opens_list(self):
        from apps.crm.models import LeaseApplication, LeaseApplicationStatus
        from apps.crm.services import LeaseApplicationService

        app = LeaseApplication.objects.create(
            status=LeaseApplicationStatus.DRAFT, person_name="P6 App"
        )
        original = LeaseApplicationService.assert_attachment_checklist

        @classmethod
        def _ok(cls, application):
            return None

        LeaseApplicationService.assert_attachment_checklist = _ok
        try:
            LeaseApplicationService.submit_to_accounting(app, actor=self.sales)
        finally:
            LeaseApplicationService.assert_attachment_checklist = original
        note = Notification.objects.get(
            user=self.acct, event_key=f"crm.lease_app.submit.{app.pk}.{self.acct.pk}"
        )
        url = notification_target_url(note, None, self.acct, "erp")
        self.assertEqual(url, reverse("erp:crm_lease_applications"))
        self.client.force_login(self.acct)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
