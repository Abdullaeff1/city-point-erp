"""Financial authorization closeout — historical evidence, priced escalation, concurrency."""

from __future__ import annotations

import threading
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.core.services import DomainError
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.maintenance.services import next_wo_code
from apps.parties.models import Party, PartyRole, PartyRoleCode
from apps.procurement.models import PurchaseApprovalLimit, PurchaseOrder, PurchaseRequest
from apps.procurement.services import (
    WF_PROCUREMENT_COMMITMENT,
    ProcurementService,
)
from apps.rbac.services import seed_rbac_catalog
from apps.warehouse.models import SKU
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class HistoricalApprovalEvidenceTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.admin = User.objects.create_user(
            username="hist-admin",
            email="hist-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.fm = User.objects.create_user(
            username="hist-fm",
            email="hist-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.sku = SKU.objects.create(code="HIST-SKU", name="H", unit="ədəd", reorder_level=1)
        self.wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="HIST",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("1000"), "is_active": True},
        )
        self.supplier = Party.objects.create(legal_name="HIST Supplier")
        PartyRole.objects.get_or_create(party=self.supplier, role=PartyRoleCode.SUPPLIER)

    def _legacy_approved(self, pr, *, amount: str):
        """Simulate pre-fix payload: amount+AZN without verified provenance."""
        req = ApprovalService.request(
            workflow_code="procurement.pr",
            requested_by=self.fm,
            entity=pr,
            payload={
                "pr_id": pr.pk,
                "code": pr.code,
                "amount": amount,
                "currency": "AZN",
                # intentionally omit decision_scope / amount_basis
            },
        )
        ApprovalService.decide(req, approved=True, decided_by=self.admin, comment="legacy")
        pr.status = "approved"
        pr.save(update_fields=["status"])
        return req

    def test_large_legacy_qty_not_spending_ceiling(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="legacy-big", qty="1", sku=self.sku
        )
        self._legacy_approved(pr, amount="9000")
        self.assertIsNone(
            ProcurementService.verified_spending_ceiling(
                ProcurementService.latest_pr_approval_payload(pr)
            )
        )
        # 8000 would be "within" a fake 9000 ceiling — must still escalate on role limit.
        with self.assertRaises(DomainError) as ctx:
            ProcurementService.create_po_from_pr(
                pr, supplier_party=self.supplier, actor=self.fm, unit_price="8000"
            )
        self.assertIn("öhdəlik sorğusu", str(ctx.exception))
        self.assertTrue(
            ApprovalRequest.objects.filter(
                workflow_code=WF_PROCUREMENT_COMMITMENT,
                status=ApprovalStatus.PENDING,
                entity_id=pr.pk,
            ).exists()
        )

    def test_small_legacy_qty_not_spending_ceiling(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="legacy-small", qty="1", sku=self.sku
        )
        self._legacy_approved(pr, amount="2")
        # Fake ceiling of 2 AZN must not block-or-allow as money; role limit 1000 applies.
        po = ProcurementService.create_po_from_pr(
            pr, supplier_party=self.supplier, actor=self.fm, unit_price="200"
        )
        self.assertEqual(ProcurementService.assess_po_amount(po).amount, Decimal("200.00"))

    def test_report_lists_unverified(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="report", qty="1", sku=self.sku
        )
        self._legacy_approved(pr, amount="50")
        rows = list(ProcurementService.iter_unverified_historical_approvals())
        self.assertTrue(any(r["pr_id"] == pr.pk and r["amount"] == "50" for r in rows))


class PricedEscalationPathTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.fm = User.objects.create_user(
            username="esc-fm",
            email="esc-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.mgmt = User.objects.create_user(
            username="esc-mgmt",
            email="esc-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="esc-admin",
            email="esc-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.sku = SKU.objects.create(code="ESC-SKU", name="E", unit="ədəd", reorder_level=1)
        self.wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="ESC",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("1000"), "is_active": True},
        )
        self.supplier = Party.objects.create(legal_name="ESC Supplier")
        PartyRole.objects.get_or_create(party=self.supplier, role=PartyRoleCode.SUPPLIER)

    def test_8000_quote_escalates_mgmt_approves_fm_issues_po(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="capex", qty="1", sku=self.sku
        )
        ProcurementService.approve_pr(pr, actor=self.admin)  # process_only
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        quote = ProcurementService.add_rfq_quote(
            rfq, supplier_party=self.supplier, unit_price="8000", actor=self.fm
        )

        with self.assertRaises(DomainError) as ctx:
            ProcurementService.select_rfq_quote_and_create_po(quote, actor=self.fm)
        self.assertIn("8000", str(ctx.exception))
        req = ApprovalRequest.objects.get(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            status=ApprovalStatus.PENDING,
            entity_id=pr.pk,
        )
        self.assertEqual(req.payload.get("amount"), "8000.00")
        self.assertEqual(req.payload.get("decision_scope"), "process_and_amount")
        self.assertEqual(req.payload.get("tax_basis"), "unspecified")
        self.assertEqual(req.payload.get("quote_id"), quote.pk)

        # Hub visibility
        self.client.force_login(self.mgmt)
        hub = self.client.get(reverse("erp:approvals"))
        self.assertContains(hub, "Satınalma öhdəlik")
        self.assertContains(hub, "8000")
        decide = self.client.post(
            reverse("erp:approvals"),
            {"action": "approve", "approval_id": req.pk, "comment": "capex ok"},
        )
        self.assertEqual(decide.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.APPROVED)

        # Idempotent second decide
        again = self.client.post(
            reverse("erp:approvals"),
            {"action": "reject", "approval_id": req.pk},
        )
        self.assertEqual(again.status_code, 404)

        po = ProcurementService.select_rfq_quote_and_create_po(quote, actor=self.fm)
        self.assertEqual(ProcurementService.assess_po_amount(po).amount, Decimal("8000.00"))
        req.refresh_from_db()
        self.assertEqual(req.payload.get("consumed_po_id"), po.pk)

        # Consumed approval: same quote retry must not create a second PO
        po_count = PurchaseOrder.objects.filter(pr=pr).count()
        self.assertEqual(po_count, 1)
        with self.assertRaises(DomainError):
            ProcurementService.select_rfq_quote_and_create_po(quote, actor=self.fm)
        self.assertEqual(PurchaseOrder.objects.filter(pr=pr).count(), 1)
        req.refresh_from_db()
        self.assertEqual(req.payload.get("consumed_po_id"), po.pk)

        # Price change before issue of a new quote requires fresh approval
        quote2 = ProcurementService.add_rfq_quote(
            rfq, supplier_party=self.supplier, unit_price="8100", actor=self.fm
        )
        with self.assertRaises(DomainError):
            ProcurementService.select_rfq_quote_and_create_po(quote2, actor=self.fm)

    def test_admin_override_audited(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="ovr", qty="1", sku=self.sku
        )
        ProcurementService.approve_pr(pr, actor=self.admin)
        before = AuditLog.objects.filter(action="procurement.commitment.admin_override").count()
        po = ProcurementService.create_po_from_pr(
            pr, supplier_party=self.supplier, actor=self.admin, unit_price="8000"
        )
        self.assertIsNotNone(po.pk)
        after = AuditLog.objects.filter(action="procurement.commitment.admin_override").count()
        self.assertEqual(after, before + 1)


class CommitmentConcurrencyTests(TransactionTestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.fm = User.objects.create_user(
            username="conc-fm",
            email="conc-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="conc-admin",
            email="conc-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.sku = SKU.objects.create(code="CONC-SKU", name="C", unit="ədəd", reorder_level=1)
        self.wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="CONC",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("1000"), "is_active": True},
        )
        self.supplier = Party.objects.create(legal_name="CONC Supplier")
        PartyRole.objects.get_or_create(party=self.supplier, role=PartyRoleCode.SUPPLIER)
        self.pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="race", qty="1", sku=self.sku
        )
        ProcurementService.approve_pr(self.pr, actor=self.admin)

    def test_concurrent_700_plus_700_one_succeeds(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-level locks")

        pr_id = self.pr.pk
        supplier_id = self.supplier.pk
        fm_id = self.fm.pk
        barrier = threading.Barrier(2, timeout=20)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker(mode: str):
            connections.close_all()
            try:
                barrier.wait()
                actor = User.objects.get(pk=fm_id)
                supplier = Party.objects.get(pk=supplier_id)
                pr = PurchaseRequest.objects.get(pk=pr_id)
                if mode == "direct":
                    ProcurementService.create_po_from_pr(
                        pr, supplier_party=supplier, actor=actor, unit_price="700"
                    )
                else:
                    rfq = ProcurementService.create_rfq_from_pr(pr, actor=actor)
                    quote = ProcurementService.add_rfq_quote(
                        rfq, supplier_party=supplier, unit_price="700", actor=actor
                    )
                    ProcurementService.select_rfq_quote_and_create_po(quote, actor=actor)
                with lock:
                    outcomes.append(f"ok:{mode}")
            except DomainError as exc:
                with lock:
                    outcomes.append(f"err:{mode}:{exc}")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    outcomes.append(f"{type(exc).__name__}:{mode}:{exc}")
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=("direct",)),
            threading.Thread(target=worker, args=("quote",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
            self.assertFalse(t.is_alive())

        ok = [o for o in outcomes if o.startswith("ok:")]
        err = [o for o in outcomes if o.startswith("err:")]
        self.assertEqual(len(ok), 1, outcomes)
        self.assertEqual(len(err), 1, outcomes)
        pos = PurchaseOrder.objects.filter(pr_id=pr_id).exclude(status="cancelled")
        self.assertEqual(pos.count(), 1)
        committed = ProcurementService.pr_committed_amount(
            PurchaseRequest.objects.get(pk=pr_id)
        )
        self.assertEqual(committed.amount, Decimal("700.00"))
        self.assertLessEqual(committed.amount, Decimal("1000.00"))

    def test_exact_threshold_and_second_partial_within_ceiling(self):
        po1 = ProcurementService.create_po_from_pr(
            self.pr, supplier_party=self.supplier, actor=self.fm, unit_price="1000"
        )
        self.assertEqual(ProcurementService.assess_po_amount(po1).amount, Decimal("1000.00"))
        # Remaining qty is zero after full order — block before monetary micro-order.
        with self.assertRaises(DomainError) as ctx:
            ProcurementService.create_po_from_pr(
                self.pr, supplier_party=self.supplier, actor=self.fm, unit_price="0.01"
            )
        self.assertIn("qalan miqdar", str(ctx.exception).lower())

        # Fresh PR qty=2: order 1@600 then 1@400 within 1000
        pr2 = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="partial", qty="2", sku=self.sku
        )
        ProcurementService.approve_pr(pr2, actor=self.admin)
        line_id = pr2.lines.get().pk
        ProcurementService.create_po_from_pr(
            pr2,
            supplier_party=self.supplier,
            actor=self.fm,
            unit_price="600",
            line_qtys={line_id: "1"},
        )
        po2 = ProcurementService.create_po_from_pr(
            pr2,
            supplier_party=self.supplier,
            actor=self.fm,
            unit_price="400",
            line_qtys={line_id: "1"},
        )
        self.assertEqual(ProcurementService.assess_po_amount(po2).amount, Decimal("400.00"))
        self.assertEqual(
            ProcurementService.pr_committed_amount(pr2).amount, Decimal("1000.00")
        )
