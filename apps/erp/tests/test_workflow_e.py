"""Workflow E — Department → Management (document approval + PR escalation)."""

from __future__ import annotations

import threading
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.comms.models import Notification
from apps.core import events as bus
from apps.core.event_handlers import register_default_handlers
from apps.core.services import DomainError
from apps.documents.models import (
    DocumentSensitivity,
    DocumentType,
    DOCUMENT_TYPE_OTHER,
)
from apps.documents.services import WF_DOCUMENT_APPROVE, DocumentService
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.maintenance.services import next_wo_code
from apps.procurement.models import (
    PRSource,
    PRStatus,
    PurchaseApprovalLimit,
    PurchaseRequest,
)
from apps.procurement.services import ProcurementService
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.warehouse.models import SKU, Warehouse
from apps.workflows.models import ApprovalRequest, ApprovalStatus

User = get_user_model()


def _pdf(name: str, body: bytes = b"%PDF-1.4 we") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, body, content_type="application/pdf")


class WorkflowEDocumentTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        bus.clear_handlers()
        register_default_handlers()
        self.client = Client()
        self.company = ResidentCompany.objects.create(
            name="WE Docs Co", slug="we-docs", portal_active=True, is_internal=False
        )
        self.dtype, _ = DocumentType.objects.get_or_create(
            code=DOCUMENT_TYPE_OTHER,
            defaults={
                "name": "Digər",
                "requires_approval": True,
                "default_sensitivity": DocumentSensitivity.CONFIDENTIAL,
            },
        )
        self.dtype.requires_approval = True
        self.dtype.default_sensitivity = DocumentSensitivity.CONFIDENTIAL
        self.dtype.save(update_fields=["requires_approval", "default_sensitivity"])

        self.fm = User.objects.create_user(
            username="we-fm",
            email="we-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.mgmt = User.objects.create_user(
            username="we-mgmt",
            email="we-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.mgmt2 = User.objects.create_user(
            username="we-mgmt2",
            email="we-mgmt2@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="we-sales",
            email="we-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        self.resident = User.objects.create_user(
            username="we-res",
            email="we-res@test.az",
            password="x",
            role=Role.RESIDENT_USER,
        )
        self.doc = DocumentService.upload_new(
            title="WE Müqavilə",
            uploaded_file=_pdf("we-v1.pdf", b"%PDF-1.4 v1-content"),
            company=self.company,
            document_type=self.dtype,
            created_by=self.fm,
        )

    def tearDown(self):
        bus.clear_handlers()
        register_default_handlers()

    def test_a_document_submit_approve_visible_to_department(self):
        self.client.force_login(self.fm)
        resp = self.client.post(
            reverse("erp:documents"),
            {"action": "submit_approval", "document_id": self.doc.pk},
        )
        self.assertEqual(resp.status_code, 302)
        pending = ApprovalRequest.objects.filter(
            workflow_code=WF_DOCUMENT_APPROVE, status=ApprovalStatus.PENDING
        )
        self.assertEqual(pending.count(), 1)
        req = pending.get()
        self.assertEqual(req.payload.get("version_label"), "1")
        self.assertEqual(req.payload.get("document_id"), self.doc.pk)

        self.client.force_login(self.mgmt)
        hub = self.client.get(reverse("erp:approvals"))
        self.assertEqual(hub.status_code, 200)
        self.assertContains(hub, "Sənəd")
        self.assertContains(hub, "WE Müqavilə")
        self.assertEqual(len(hub.context["pending"]), 1)

        dl = self.client.get(
            reverse("erp:document_download", kwargs={"pk": self.doc.pk})
            + f"?version={req.payload['version_id']}"
        )
        self.assertEqual(dl.status_code, 200)

        decide = self.client.post(
            reverse("erp:approvals"),
            {"action": "approve", "approval_id": req.pk, "comment": "ok v1"},
        )
        self.assertEqual(decide.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.APPROVED)
        self.assertEqual(req.payload.get("version_label"), "1")

        notes = Notification.objects.filter(user=self.fm)
        self.assertTrue(notes.filter(message__icontains="təsdiqləndi").exists())

        # Decision 08: the global archive list is Management/Admin only.
        self.client.force_login(self.fm)
        self.assertEqual(self.client.get(reverse("erp:documents")).status_code, 302)
        self.client.force_login(self.mgmt)
        listing = self.client.get(reverse("erp:documents"))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "Təsdiqlənib")
        self.assertContains(listing, "v1")

    def test_b_reject_shows_reason_and_allows_resubmit(self):
        req = DocumentService.submit_for_approval(self.doc, actor=self.fm)
        self.client.force_login(self.mgmt)
        self.client.post(
            reverse("erp:approvals"),
            {"action": "reject", "approval_id": req.pk, "comment": "imza çatışmır"},
        )
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.REJECTED)

        self.client.force_login(self.mgmt)
        page = self.client.get(reverse("erp:documents"))
        self.assertContains(page, "imza çatışmır")
        self.assertContains(page, "Rədd")

        # Resubmit same version after reject
        req2 = DocumentService.submit_for_approval(self.doc, actor=self.fm)
        self.assertEqual(req2.status, ApprovalStatus.PENDING)
        self.assertNotEqual(req2.pk, req.pk)

    def test_c_version2_cancels_pending_v1_decision_stays_bound(self):
        req_v1 = DocumentService.submit_for_approval(self.doc, actor=self.fm)
        v1_id = req_v1.payload["version_id"]
        DocumentService.add_version(
            self.doc,
            uploaded_file=_pdf("we-v2.pdf", b"%PDF-1.4 v2-content"),
            created_by=self.fm,
            label="2",
        )
        req_v1.refresh_from_db()
        self.assertEqual(req_v1.status, ApprovalStatus.CANCELLED)
        self.assertEqual(req_v1.payload.get("version_id"), v1_id)

        pending = DocumentService.pending_approval_for_document(self.doc)
        self.assertIsNone(pending)

        req_v2 = DocumentService.submit_for_approval(self.doc, actor=self.fm)
        self.assertEqual(req_v2.payload.get("version_label"), "2")
        DocumentService.decide_approval(
            req_v2, actor=self.mgmt, approved=True, comment="v2 ok"
        )
        req_v2.refresh_from_db()
        self.assertEqual(req_v2.status, ApprovalStatus.APPROVED)
        self.assertEqual(req_v2.payload.get("version_label"), "2")
        # Historical v1 request never silently becomes an approval of v2
        req_v1.refresh_from_db()
        self.assertEqual(req_v1.status, ApprovalStatus.CANCELLED)
        self.assertEqual(req_v1.payload.get("version_label"), "1")

    def test_h_unrelated_and_resident_denied(self):
        req = DocumentService.submit_for_approval(self.doc, actor=self.fm)

        self.client.force_login(self.sales)
        # Sales has document.view but CONFIDENTIAL download is denied (soft 403 → redirect).
        dl = self.client.get(reverse("erp:document_download", kwargs={"pk": self.doc.pk}))
        self.assertIn(dl.status_code, (302, 403))
        decide = self.client.post(
            reverse("erp:approvals"),
            {"action": "approve", "approval_id": req.pk},
        )
        self.assertIn(decide.status_code, (302, 403))
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.PENDING)

        self.client.force_login(self.resident)
        dl2 = self.client.get(reverse("erp:document_download", kwargs={"pk": self.doc.pk}))
        self.assertIn(dl2.status_code, (302, 403))
        hub = self.client.get(reverse("erp:approvals"))
        self.assertIn(hub.status_code, (302, 403))
        # Decision must remain pending after unauthorized attempts
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.PENDING)

    def test_duplicate_submit_idempotent_same_version(self):
        r1 = DocumentService.submit_for_approval(self.doc, actor=self.fm)
        r2 = DocumentService.submit_for_approval(self.doc, actor=self.fm)
        self.assertEqual(r1.pk, r2.pk)
        self.assertEqual(
            ApprovalRequest.objects.filter(
                workflow_code=WF_DOCUMENT_APPROVE, status=ApprovalStatus.PENDING
            ).count(),
            1,
        )


class WorkflowEProcurementTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        bus.clear_handlers()
        register_default_handlers()
        self.client = Client()
        self.fm = User.objects.create_user(
            username="we-p-fm",
            email="we-p-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(self.fm, "supply.head")
        self.mgmt = User.objects.create_user(
            username="we-p-mgmt",
            email="we-p-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="we-p-admin",
            email="we-p-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.wh = Warehouse.objects.create(code="WE-WH", name="WE WH")
        self.sku = SKU.objects.create(code="WE-SKU", name="Widget", unit="ədəd", reorder_level=10)
        self.wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="WE WO",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("1000"), "is_active": True},
        )

    def tearDown(self):
        bus.clear_handlers()
        register_default_handlers()

    def test_d_unpriced_pr_escalates_not_local_qty(self):
        """Without PR unit prices, FM cannot locally approve (qty is not AZN)."""
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="unpriced", qty="4", sku=self.sku
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.SUBMITTED)
        req = ApprovalRequest.objects.get(
            workflow_code="procurement.pr",
            status=ApprovalStatus.PENDING,
            entity_id=pr.pk,
        )
        self.assertEqual(req.payload.get("escalation_reason"), "amount_unknown")
        self.assertEqual(req.payload.get("amount"), "")

    def test_e_hub_shows_amount_unknown_not_qty_as_azn(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="hub-amt", qty="6", sku=self.sku
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        req = ApprovalRequest.objects.get(
            workflow_code="procurement.pr",
            status=ApprovalStatus.PENDING,
            entity_id=pr.pk,
        )
        self.assertEqual(req.payload.get("amount"), "")
        self.assertEqual(req.payload.get("currency"), "")

        PurchaseApprovalLimit.objects.filter(role=Role.SERVICE_DESK).delete()
        pr_miss = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="miss", qty="1", sku=self.sku
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr_miss, actor=self.fm)
        miss_req = ApprovalRequest.objects.get(
            workflow_code="procurement.pr",
            status=ApprovalStatus.PENDING,
            entity_id=pr_miss.pk,
        )
        # Still amount_unknown at PR stage (no price); limit_missing applies once money exists.
        self.assertEqual(miss_req.payload.get("escalation_reason"), "amount_unknown")

        self.client.force_login(self.mgmt)
        hub = self.client.get(reverse("erp:approvals"))
        self.assertContains(hub, "Məbləğ müəyyən edilməyib")
        self.assertNotContains(hub, "6 AZN")

    def test_f_manual_blocked_for_fm_even_below_limit(self):
        pr = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="Manual WE",
            lines=[{"description": "pen", "qty": "1"}],
        )
        self.assertEqual(pr.source, PRSource.MANUAL)
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.SUBMITTED)
        self.assertFalse(
            ApprovalRequest.objects.filter(
                workflow_code="procurement.pr",
                status=ApprovalStatus.PENDING,
                entity_id=pr.pk,
            ).exists()
        )

    def test_g_management_hub_approve_enables_po_reject_blocks(self):
        from apps.parties.models import Party, PartyRole, PartyRoleCode

        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="esc", qty="20", sku=self.sku
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        req = ApprovalRequest.objects.get(
            workflow_code="procurement.pr", status=ApprovalStatus.PENDING, entity_id=pr.pk
        )

        self.client.force_login(self.mgmt)
        hub = self.client.get(reverse("erp:approvals"))
        self.assertContains(hub, "Satınalma")
        self.assertContains(hub, pr.code)
        self.assertContains(hub, "Məbləğ müəyyən edilməyib")
        resp = self.client.post(
            reverse("erp:approvals"),
            {"action": "approve", "approval_id": req.pk, "comment": "capex ok"},
        )
        self.assertEqual(resp.status_code, 302)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.APPROVED)
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.APPROVED)

        supplier = Party.objects.create(legal_name="WE Supplier")
        PartyRole.objects.get_or_create(party=supplier, role=PartyRoleCode.SUPPLIER)
        po = ProcurementService.create_po_from_pr(pr, supplier_party=supplier, actor=self.fm)
        self.assertIsNotNone(po.pk)

        pr_rej = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="rej", qty="30", sku=self.sku
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr_rej, actor=self.fm)
        req_rej = ApprovalRequest.objects.get(
            workflow_code="procurement.pr",
            status=ApprovalStatus.PENDING,
            entity_id=pr_rej.pk,
        )
        self.client.post(
            reverse("erp:approvals"),
            {"action": "reject", "approval_id": req_rej.pk, "comment": "büdcə yox"},
        )
        pr_rej.refresh_from_db()
        self.assertEqual(pr_rej.status, PRStatus.REJECTED)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr_rej, supplier_party=supplier, actor=self.fm
            )

    def test_unusable_amount_escalates_not_local_zero(self):
        pr = PurchaseRequest.objects.create(
            code="PR-WE-EMPTY",
            title="Empty lines",
            status=PRStatus.SUBMITTED,
            requested_by=self.fm,
            source=PRSource.WO,
            work_order=self.wo,
        )
        self.assertIsNone(ProcurementService.pr_estimated_amount(pr))
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        pending = ApprovalRequest.objects.filter(
            workflow_code="procurement.pr", status=ApprovalStatus.PENDING, entity_id=pr.pk
        )
        self.assertEqual(pending.count(), 1)
        self.assertEqual(pending.get().payload.get("escalation_reason"), "empty_request")

    def test_hub_counts_include_procurement_and_docs(self):
        from apps.erp.management_hub import build_management_hub

        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="hub", qty="9", sku=self.sku
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        hub = build_management_hub(self.mgmt)
        self.assertGreaterEqual(hub["pending_procurement"], 1)
        self.assertGreaterEqual(hub["pending_total"], hub["pending_procurement"])

    def test_repeated_decision_post_is_safe(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="stale", qty="11", sku=self.sku
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        req = ApprovalRequest.objects.get(
            workflow_code="procurement.pr",
            status=ApprovalStatus.PENDING,
            entity_id=pr.pk,
        )
        self.client.force_login(self.mgmt)
        url = reverse("erp:approvals")
        r1 = self.client.post(url, {"action": "approve", "approval_id": req.pk})
        self.assertEqual(r1.status_code, 302)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.APPROVED)
        # Stale tab: second POST looks up PENDING only → 404, source stays approved.
        r2 = self.client.post(url, {"action": "reject", "approval_id": req.pk})
        self.assertEqual(r2.status_code, 404)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.APPROVED)
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.APPROVED)


class WorkflowEConcurrencyTests(TransactionTestCase):
    def setUp(self):
        seed_rbac_catalog()
        bus.clear_handlers()
        register_default_handlers()
        self.fm = User.objects.create_user(
            username="we-c-fm",
            email="we-c-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.m1 = User.objects.create_user(
            username="we-c-m1",
            email="we-c-m1@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.m2 = User.objects.create_user(
            username="we-c-m2",
            email="we-c-m2@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="WE Conc",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        self.sku = SKU.objects.create(code="WE-C-SKU", name="C", unit="ədəd", reorder_level=1)
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("1"), "is_active": True},
        )
        self.pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="race", qty="10", sku=self.sku
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(self.pr, actor=self.fm)
        self.req = ApprovalRequest.objects.get(
            workflow_code="procurement.pr",
            status=ApprovalStatus.PENDING,
            entity_id=self.pr.pk,
        )

    def tearDown(self):
        bus.clear_handlers()
        register_default_handlers()
        ContentType.objects.clear_cache()
        connections.close_all()

    def test_i_concurrent_approve_reject_one_terminal(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-level locks")

        req_id = self.req.pk
        pr_id = self.pr.pk
        m1_id = self.m1.pk
        m2_id = self.m2.pk
        fm_id = self.fm.pk
        barrier = threading.Barrier(2, timeout=20)
        results: list[str] = []
        lock = threading.Lock()

        def worker(*, approved: bool, actor_id: int, label: str):
            connections.close_all()
            try:
                barrier.wait()
                actor = User.objects.get(pk=actor_id)
                req = ApprovalRequest.objects.get(pk=req_id)
                ProcurementService.decide_management_pr(
                    req, approved=approved, actor=actor, comment=label
                )
                with lock:
                    results.append(label)
            except DomainError as exc:
                with lock:
                    results.append(f"err:{exc}")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    results.append(f"{type(exc).__name__}:{exc}")
            finally:
                connections.close_all()

        threads = [
            threading.Thread(
                target=worker, kwargs={"approved": True, "actor_id": m1_id, "label": "approved"}
            ),
            threading.Thread(
                target=worker, kwargs={"approved": False, "actor_id": m2_id, "label": "rejected"}
            ),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
            self.assertFalse(t.is_alive(), "worker hung")

        req = ApprovalRequest.objects.get(pk=req_id)
        pr = PurchaseRequest.objects.get(pk=pr_id)
        self.assertIn(req.status, {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED})
        if req.status == ApprovalStatus.APPROVED:
            self.assertEqual(pr.status, PRStatus.APPROVED)
        else:
            self.assertEqual(pr.status, PRStatus.REJECTED)
        terminals = [r for r in results if r in {"approved", "rejected"}]
        self.assertEqual(len(terminals), 1, results)
        self.assertTrue(any(str(r).startswith("err:") for r in results), results)

        stamp = req.decided_at.isoformat()
        key = f"approval.decided.{req.pk}.{req.status}.{stamp}"
        fm = User.objects.get(pk=fm_id)
        count = Notification.objects.filter(user=fm, event_key=key).count()
        self.assertEqual(count, 1)
        bus.emit(
            bus.APPROVAL_DECIDED,
            payload={
                "approval_id": req.pk,
                "workflow_code": req.workflow_code,
                "status": req.status,
            },
            event_key=key,
        )
        self.assertEqual(Notification.objects.filter(user=fm, event_key=key).count(), 1)
