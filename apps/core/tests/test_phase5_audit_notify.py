"""Phase 5 — Audit history and in-app notifications across workflows A–E."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.test_utils import ensure_portal_membership
from apps.audit.models import AuditLog
from apps.comms.links import notification_target_url, user_notifications
from apps.comms.models import Notification
from apps.comms.services import notify_in_app
from apps.core import events as bus
from apps.core.event_handlers import register_default_handlers
from apps.core.services import DomainError
from apps.crm.models import LeaseApplication, LeaseApplicationStatus
from apps.crm.services import LeaseApplicationService
from apps.documents.models import DOCUMENT_TYPE_OTHER, DocumentSensitivity, DocumentType
from apps.documents.services import DocumentService
from apps.leases.models import Lease, LeaseStatus
from apps.leases.services import mark_lease_expiring, process_lease_lifecycle
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.maintenance.services import WorkOrderService, next_wo_code
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType
from apps.procurement.models import PurchaseApprovalLimit
from apps.procurement.services import ProcurementService
from apps.property.models import (
    Building,
    CommercialStatus,
    Floor,
    Occupancy,
    OperationalStatus,
    Space,
)
from apps.rbac.services import seed_rbac_catalog
from apps.reception.models import (
    Guest,
    GuestVisit,
    SyncStatus,
    VisitStatus,
    VisitorAccess,
    VisitorAccessStatus,
)
from apps.reception.services import checkout_guests_from_access_events
from apps.residents.models import AccessEvent, AccessEventType, AccessResult, ResidentCompany
from apps.tickets.models import TicketDepartment, TicketStatus, TicketSubcategory, TicketType
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import (
    create_ticket_from_portal,
    create_work_order_from_ticket,
    set_ticket_status,
)
from apps.warehouse.models import SKU, Stock, Warehouse
from apps.warehouse.services import confirm_issue, request_issue_line
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class Phase5AuditNotifyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        seed_ticket_taxonomy()
        cls.co_a = ResidentCompany.objects.create(
            name="P5 Co A", slug="p5-a", portal_active=True, is_internal=False
        )
        cls.co_b = ResidentCompany.objects.create(
            name="P5 Co B", slug="p5-b", portal_active=True, is_internal=False
        )
        cls.hvac = TicketSubcategory.objects.get(slug="hvac", is_active=True)
        cls.desk_dept = TicketDepartment.objects.get(code="servicedesk")
        cls.fm_dept = TicketDepartment.objects.get(code="webservis")
        cls.sec_dept = TicketDepartment.objects.get(code="security")

    def setUp(self):
        bus.clear_handlers()
        register_default_handlers()
        self.client = Client()
        self.cat = self.hvac.category
        self.sub = self.hvac
        self.mgmt = User.objects.create_user(
            username="p5-mgmt",
            email="p5-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.fm = User.objects.create_user(
            username="p5-fm",
            email="p5-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=self.fm_dept,
        )
        self.desk = User.objects.create_user(
            username="p5-desk",
            email="p5-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
            ticket_department=self.desk_dept,
        )
        self.sales = User.objects.create_user(
            username="p5-sales",
            email="p5-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        self.acct = User.objects.create_user(
            username="p5-acct",
            email="p5-acct@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        self.sec = User.objects.create_user(
            username="p5-sec",
            email="p5-sec@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
            ticket_department=self.sec_dept,
        )
        self.admin = User.objects.create_user(
            username="p5-adm",
            email="p5-adm@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.res_a = User.objects.create_user(
            username="p5-resa",
            email="p5-resa@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co_a,
        )
        ensure_portal_membership(self.res_a, self.co_a)
        self.res_b = User.objects.create_user(
            username="p5-resb",
            email="p5-resb@test.az",
            password="x",
            role=Role.RESIDENT_USER,
            resident_company=self.co_b,
        )
        ensure_portal_membership(self.res_b, self.co_b)
        self.wh = Warehouse.objects.create(code="P5WH", name="P5 WH")
        self.sku = SKU.objects.create(
            code="P5-SKU", name="Filter", unit="ədəd", reorder_level=0
        )
        Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("20"))
        self.supplier = Party.objects.create(legal_name="P5 Supplier")
        PartyRole.objects.get_or_create(party=self.supplier, role=PartyRoleCode.SUPPLIER)
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("1000"), "is_active": True},
        )

    def tearDown(self):
        bus.clear_handlers()
        register_default_handlers()

    def test_A_document_decide_audit_and_originator_notify(self):
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
            title="P5 Policy",
            uploaded_file=SimpleUploadedFile(
                "p5.pdf", b"%PDF-1.4 p5", content_type="application/pdf"
            ),
            company=self.co_a,
            document_type=dtype,
            created_by=self.fm,
        )
        req = DocumentService.submit_for_approval(doc, actor=self.fm)
        version_id = (req.payload or {}).get("version_id")
        self.assertIsNotNone(version_id)
        decided = DocumentService.decide_approval(
            req, actor=self.mgmt, approved=True, comment="ok"
        )
        self.assertEqual(decided.status, ApprovalStatus.APPROVED)
        audit = AuditLog.objects.filter(
            action="document.approval_decided", entity_id=doc.pk
        ).latest("id")
        self.assertEqual(audit.new_values.get("version_id"), version_id)
        note = Notification.objects.filter(
            user=self.fm, event_key__startswith=f"approval.decided.{req.pk}."
        ).latest("id")
        self.assertIn(str(version_id), note.message)
        self.assertIn("təsdiqləndi", note.message)

    def test_B_process_only_vs_priced_commitment_messages(self):
        wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="P5",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        pr = ProcurementService.create_pr_for_work_order(
            wo, actor=self.fm, description="capex", qty="1", sku=self.sku
        )
        ProcurementService.approve_pr(pr, actor=self.admin)
        purchase_notes = Notification.objects.filter(
            user=self.fm, event_key=f"purchase.approved.{pr.pk}"
        )
        self.assertTrue(purchase_notes.exists())
        self.assertIn("məbləğ səlahiyyəti", purchase_notes.first().message)

        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        quote = ProcurementService.add_rfq_quote(
            rfq, supplier_party=self.supplier, unit_price="8000", actor=self.fm
        )
        with self.assertRaises(DomainError):
            ProcurementService.select_rfq_quote_and_create_po(quote, actor=self.fm)
        req = ApprovalRequest.objects.get(
            workflow_code="procurement.commitment",
            status=ApprovalStatus.PENDING,
            entity_id=pr.pk,
        )
        ApprovalService.decide(req, approved=True, decided_by=self.mgmt, comment="capex")
        commit_note = Notification.objects.filter(
            user=self.fm, event_key__startswith=f"approval.decided.{req.pk}."
        ).latest("id")
        self.assertIn("8000", commit_note.message)
        self.assertIn("maliyyə öhdəliyi", commit_note.message)

    def test_C_wo_complete_notifies_helpdesk_resident_limited(self):
        ticket = create_ticket_from_portal(
            company=self.co_a,
            requester=self.res_a,
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.sub,
            description="AC broken",
        )
        ticket.assignee = self.desk
        ticket.save(update_fields=["assignee"])
        wo = create_work_order_from_ticket(ticket, actor=self.desk)
        WorkOrderService.set_status(
            wo, WorkOrderStatus.COMPLETED, actor=self.fm, note="Tech done"
        )
        helpdesk_notes = Notification.objects.filter(
            user=self.desk, event_key__startswith=f"wo.closed.helpdesk.{wo.pk}"
        )
        self.assertTrue(helpdesk_notes.exists())
        target = notification_target_url(helpdesk_notes.first(), ticket, self.desk, "erp")
        self.assertIn(ticket.code, target)

        if ticket.status != TicketStatus.IN_PROGRESS:
            if ticket.status == TicketStatus.SENT:
                set_ticket_status(ticket, TicketStatus.ACCEPTED, actor=self.desk)
            set_ticket_status(ticket, TicketStatus.IN_PROGRESS, actor=self.desk)
        set_ticket_status(
            ticket, TicketStatus.RESOLVED, actor=self.desk, note="Fixed for resident"
        )
        ticket.enrichment_notes = "Internal serial SECRET99"
        ticket.save(update_fields=["enrichment_notes"])
        self.client.force_login(self.res_a)
        page = self.client.get(reverse("portal:request_detail", kwargs={"code": ticket.code}))
        self.assertContains(page, "Fixed for resident")
        self.assertNotContains(page, "SECRET99")
        self.assertNotContains(page, wo.code)

    def test_D_resolve_reopen_resolve_history_and_dedupe(self):
        ticket = create_ticket_from_portal(
            company=self.co_a,
            requester=self.res_a,
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.sub,
            description="Noise",
        )
        set_ticket_status(ticket, TicketStatus.ACCEPTED, actor=self.desk)
        set_ticket_status(ticket, TicketStatus.IN_PROGRESS, actor=self.desk)
        set_ticket_status(ticket, TicketStatus.RESOLVED, actor=self.desk, note="First fix")
        self.assertEqual(
            AuditLog.objects.filter(action=bus.TICKET_RESOLVED, entity_id=ticket.pk).count(),
            1,
        )
        self.assertEqual(
            Notification.objects.filter(
                user=self.res_a, event_key__startswith=f"ticket.resolved.{ticket.pk}."
            ).count(),
            1,
        )
        set_ticket_status(ticket, TicketStatus.RESOLVED, actor=self.desk, note="retry")
        self.assertEqual(
            AuditLog.objects.filter(action=bus.TICKET_RESOLVED, entity_id=ticket.pk).count(),
            1,
        )
        set_ticket_status(ticket, TicketStatus.REOPENED, actor=self.desk, note="reopen")
        self.assertTrue(
            AuditLog.objects.filter(action="ticket.reopened", entity_id=ticket.pk).exists()
        )
        set_ticket_status(ticket, TicketStatus.IN_PROGRESS, actor=self.desk)
        set_ticket_status(ticket, TicketStatus.RESOLVED, actor=self.desk, note="Second fix")
        self.assertEqual(
            AuditLog.objects.filter(action=bus.TICKET_RESOLVED, entity_id=ticket.pk).count(),
            2,
        )
        self.assertEqual(
            Notification.objects.filter(
                user=self.res_a, event_key__startswith=f"ticket.resolved.{ticket.pk}."
            ).count(),
            2,
        )

    def test_E_receipt_replay_and_two_partials(self):
        wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="recv",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        pr = ProcurementService.create_pr_for_work_order(
            wo, actor=self.fm, description="parts", qty="10", sku=self.sku
        )
        ProcurementService.approve_pr(pr, actor=self.admin)
        po = ProcurementService.create_po_from_pr(
            pr, supplier_party=self.supplier, actor=self.admin, unit_price="10"
        )
        line = po.lines.get()
        key1 = uuid.uuid4().hex
        key2 = uuid.uuid4().hex
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4"},
            operation_key=key1,
            receive_mode="partial",
        )
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "6"},
            operation_key=key2,
            receive_mode="partial",
        )
        audits = list(AuditLog.objects.filter(action=bus.PO_RECEIVED, entity_id=po.pk))
        self.assertEqual(len(audits), 2)
        self.assertEqual({a.new_values.get("operation_key") for a in audits}, {key1, key2})
        notes = Notification.objects.filter(
            user=self.fm, event_key__startswith=f"po.received.notify.{po.pk}."
        )
        self.assertEqual(notes.count(), 2)
        before = len(audits)
        replay = ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4"},
            operation_key=key1,
            receive_mode="partial",
        )
        self.assertTrue(getattr(replay, "receipt_replayed", False))
        self.assertEqual(
            AuditLog.objects.filter(action=bus.PO_RECEIVED, entity_id=po.pk).count(), before
        )
        self.assertEqual(notes.count(), 2)

    def test_F_axtrax_exit_source_and_no_sensitive_preview(self):
        guest = Guest.objects.create(
            first_name="Ali", last_name="Qonaq", fin_code="AZE1234567"
        )
        visit = GuestVisit.objects.create(
            guest=guest,
            company=self.co_a,
            status=VisitStatus.INSIDE,
            check_in_at=timezone.now() - timedelta(hours=1),
            id_document_held=True,
        )
        VisitorAccess.objects.create(
            visit=visit,
            credential="991122",
            status=VisitorAccessStatus.ACTIVE,
            sync_status=SyncStatus.SUCCESS,
            valid_from=visit.check_in_at,
        )
        event = AccessEvent.objects.create(
            occurred_at=timezone.now(),
            event_type=AccessEventType.OUT,
            result=AccessResult.GRANTED,
            card_number="991122",
            reader_name="Gate-1",
        )
        checkout_guests_from_access_events([event])
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.RETURN_PENDING)
        audit = AuditLog.objects.filter(
            action="visit.return_pending", entity_id=visit.pk
        ).latest("id")
        self.assertEqual(audit.new_values.get("access_event_id"), event.pk)
        self.assertEqual(audit.new_values.get("checkout_source"), "axtrax_out")
        self.assertIsNone(audit.actor_id)
        sec_note = Notification.objects.filter(
            user=self.sec, event_key__startswith=f"visitor.return_pending.{visit.pk}."
        ).first()
        self.assertIsNotNone(sec_note)
        self.assertNotIn("AZE1234567", sec_note.message)
        self.assertNotIn("991122", sec_note.message)
        self.assertIn("Ali", sec_note.message)
        before = Notification.objects.filter(
            event_key__startswith=f"visitor.return_pending.{visit.pk}."
        ).count()
        checkout_guests_from_access_events([event])
        self.assertEqual(
            Notification.objects.filter(
                event_key__startswith=f"visitor.return_pending.{visit.pk}."
            ).count(),
            before,
        )

    def test_G_cross_company_and_unauthorized_isolation(self):
        ticket = create_ticket_from_portal(
            company=self.co_a,
            requester=self.res_a,
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.sub,
            description="Private A",
        )
        self.client.force_login(self.res_b)
        denied = self.client.get(
            reverse("portal:request_detail", kwargs={"code": ticket.code})
        )
        self.assertEqual(denied.status_code, 404)
        fake = Notification(user=self.sec, message=f"x {ticket.code}", ticket=ticket)
        self.assertEqual(notification_target_url(fake, ticket, self.sec, "security"), "")
        notes_b = user_notifications(self.res_b, namespace="portal")
        for n in notes_b:
            url = getattr(n, "target_url", "") or ""
            self.assertNotIn(ticket.code, url)

    def test_H_mark_read_is_per_recipient(self):
        n1 = notify_in_app(user=self.desk, message="Desk alert", event_key="p5.read.desk")
        n2 = notify_in_app(user=self.fm, message="FM alert", event_key="p5.read.fm")
        self.client.force_login(self.desk)
        self.client.get(reverse("erp:alerts"))
        n1.refresh_from_db()
        n2.refresh_from_db()
        self.assertTrue(n1.is_read)
        self.assertFalse(n2.is_read)

    def test_I_rolled_back_transition_no_success_notify(self):
        ticket = create_ticket_from_portal(
            company=self.co_a,
            requester=self.res_a,
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.sub,
            description="rollback",
        )
        before = Notification.objects.filter(user=self.res_a).count()
        try:
            with transaction.atomic():
                set_ticket_status(ticket, TicketStatus.ACCEPTED, actor=self.desk)
                set_ticket_status(ticket, TicketStatus.IN_PROGRESS, actor=self.desk)
                set_ticket_status(
                    ticket, TicketStatus.RESOLVED, actor=self.desk, note="will rollback"
                )
                raise DomainError("force rollback")
        except DomainError:
            pass
        ticket.refresh_from_db()
        self.assertNotEqual(ticket.status, TicketStatus.RESOLVED)
        self.assertEqual(Notification.objects.filter(user=self.res_a).count(), before)
        self.assertFalse(
            AuditLog.objects.filter(
                action=bus.TICKET_RESOLVED, entity_id=ticket.pk
            ).exists()
        )

    def test_J_lease_expiry_warning_not_repeated(self):
        building = Building.objects.create(code="P5B", name="P5B")
        floor = Floor.objects.create(building=building, code="1", name="1")
        space = Space.objects.create(
            floor=floor,
            code="P5-101",
            name="101",
            area_m2=Decimal("50"),
            rentable_area_m2=Decimal("50"),
            occupancy=Occupancy.ACTIVE_LEASE,
            operational_status=OperationalStatus.AVAILABLE,
            commercial_status=CommercialStatus.ACTIVE,
            base_rent_rate=Decimal("10"),
        )
        party = Party.objects.create(
            legal_name="P5 Tenant",
            party_type=PartyType.ORGANIZATION,
            status=PartyStatus.ACTIVE,
        )
        end = timezone.localdate() + timedelta(days=14)
        lease = Lease.objects.create(
            code="LS-P5-1",
            party=party,
            space=space,
            status=LeaseStatus.ACTIVE,
            start_date=timezone.localdate() - timedelta(days=100),
            end_date=end,
            rent=Decimal("1000"),
        )
        mark_lease_expiring(lease)
        key = f"lease.expiring.{lease.pk}.{end}"
        first = Notification.objects.filter(event_key=key).count()
        self.assertGreaterEqual(first, 1)
        mark_lease_expiring(lease)
        process_lease_lifecycle(as_of=timezone.localdate(), expiring_days=30)
        self.assertEqual(Notification.objects.filter(event_key=key).count(), first)

    def test_route_and_material_issue_audited(self):
        ticket = create_ticket_from_portal(
            company=self.co_a,
            requester=self.res_a,
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.sub,
            description="route me",
        )
        self.assertTrue(
            AuditLog.objects.filter(action="ticket.route", entity_id=ticket.pk).exists()
        )
        wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="iss",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
            assigned_to=self.fm,
        )
        issue = request_issue_line(
            work_order=wo,
            warehouse=self.wh,
            sku=self.sku,
            quantity=Decimal("2"),
            actor=self.fm,
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="warehouse.issue.request", entity_id=issue.pk
            ).exists()
        )
        confirm_issue(
            issue,
            actor=self.fm,
            lines=[{"id": issue.lines.get().pk, "issued_qty": "2", "unit_cost": "5"}],
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="warehouse.issue.confirm", entity_id=issue.pk
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.fm, event_key=f"warehouse.issue.confirm.{issue.pk}"
            ).exists()
        )

    def test_accountant_notified_on_lease_app_submit(self):
        app = LeaseApplication.objects.create(
            status=LeaseApplicationStatus.DRAFT,
            person_name="P5 Applicant",
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
        self.assertTrue(
            Notification.objects.filter(
                user=self.acct, event_key=f"crm.lease_app.submit.{app.pk}.{self.acct.pk}"
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="crm.lease_app.submit", entity_id=app.pk).exists()
        )
