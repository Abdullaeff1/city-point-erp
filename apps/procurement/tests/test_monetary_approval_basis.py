"""Monetary basis for PurchaseApprovalLimit — quote/PO stage + unpriced PR escalation."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.maintenance.services import next_wo_code
from apps.parties.models import Party, PartyRole, PartyRoleCode
from apps.procurement.models import (
    PRSource,
    PRStatus,
    PurchaseApprovalLimit,
    PurchaseRequest,
)
from apps.procurement.services import ProcurementService
from apps.rbac.services import seed_rbac_catalog
from apps.warehouse.models import SKU
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class MonetaryApprovalBasisTests(TestCase):
    """Illustrative limit: 1,000 AZN (isolated tests only)."""

    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.fm = User.objects.create_user(
            username="mon-fm",
            email="mon-fm@test.az",
            password="x",
            role=Role.PROPERTY_FM,
            is_staff=True,
        )
        self.mgmt = User.objects.create_user(
            username="mon-mgmt",
            email="mon-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="mon-admin",
            email="mon-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.sku = SKU.objects.create(code="MON-SKU", name="Widget", unit="ədəd", reorder_level=1)
        self.wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="MON WO",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.PROPERTY_FM,
            defaults={"max_amount": Decimal("1000.00"), "is_active": True},
        )
        self.supplier = Party.objects.create(legal_name="MON Supplier")
        PartyRole.objects.get_or_create(party=self.supplier, role=PartyRoleCode.SUPPLIER)

    def _approve_pr_as_admin(self, pr: PurchaseRequest) -> PurchaseRequest:
        return ProcurementService.approve_pr(pr, actor=self.admin)

    def _quote_po(self, pr: PurchaseRequest, *, unit_price: str, currency: str = "AZN"):
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.admin)
        quote = ProcurementService.add_rfq_quote(
            rfq,
            supplier_party=self.supplier,
            unit_price=unit_price,
            actor=self.admin,
        )
        if currency != "AZN":
            quote.currency = currency
            quote.save(update_fields=["currency"])
        return ProcurementService.select_rfq_quote_and_create_po(quote, actor=self.fm)

    def test_a_one_unit_8000_escalates_at_quote(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="capex", qty="1", sku=self.sku
        )
        # PR stage: unpriced → escalate
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        self._approve_pr_as_admin(pr)
        with self.assertRaises(DomainError) as ctx:
            self._quote_po(pr, unit_price="8000")
        self.assertIn("8000", str(ctx.exception))
        self.assertIn("öhdəlik sorğusu", str(ctx.exception))

    def test_b_2000_units_at_010_local_quote_path(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="bulk", qty="2000", sku=self.sku
        )
        self._approve_pr_as_admin(pr)
        assessed = ProcurementService.assess_quote_amount(
            type("Q", (), {"unit_price": Decimal("0.10"), "currency": "AZN"})(),
            pr,
        )
        self.assertEqual(assessed.amount, Decimal("200.00"))
        po = self._quote_po(pr, unit_price="0.10")
        self.assertIsNotNone(po.pk)
        self.assertEqual(po.lines.get().unit_price, Decimal("0.10"))

    def test_c_threshold_1000_inclusive_and_above(self):
        pr_at = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="at", qty="1", sku=self.sku
        )
        self._approve_pr_as_admin(pr_at)
        po_at = self._quote_po(pr_at, unit_price="1000.00")
        self.assertIsNotNone(po_at.pk)

        pr_over = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="over", qty="1", sku=self.sku
        )
        self._approve_pr_as_admin(pr_over)
        with self.assertRaises(DomainError):
            self._quote_po(pr_over, unit_price="1000.01")

    def test_d_mixed_priced_unpriced_unknown_at_pr(self):
        """PR schema has no price field — any populated PR is amount_unknown."""
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="mixed", qty="5", sku=self.sku
        )
        assessed = ProcurementService.assess_pr_approval_amount(pr)
        self.assertFalse(assessed.is_known)
        self.assertEqual(assessed.reason, "amount_unknown")
        # Known subtotal cannot authorize: there is no partial priced PR total.
        self.assertIsNone(assessed.amount)

    def test_e_distinguishable_reasons(self):
        empty = PurchaseRequest.objects.create(
            code="PR-MON-EMPTY",
            title="Empty",
            status=PRStatus.SUBMITTED,
            requested_by=self.fm,
            source=PRSource.WO,
            work_order=self.wo,
        )
        self.assertEqual(ProcurementService.assess_pr_approval_amount(empty).reason, "empty_request")
        with self.assertRaises(DomainError) as ctx_empty:
            ProcurementService.approve_pr(empty, actor=self.fm)
        self.assertIn("sətiri yoxdur", str(ctx_empty.exception))

        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="unk", qty="1", sku=self.sku
        )
        with self.assertRaises(DomainError) as ctx_unk:
            ProcurementService.approve_pr(pr, actor=self.fm)
        self.assertIn("müəyyən edilməyib", str(ctx_unk.exception))
        self.assertEqual(
            ApprovalRequest.objects.get(entity_id=pr.pk, status=ApprovalStatus.PENDING).payload[
                "escalation_reason"
            ],
            "amount_unknown",
        )

        self._approve_pr_as_admin(pr)
        PurchaseApprovalLimit.objects.filter(role=Role.PROPERTY_FM).delete()
        with self.assertRaises(DomainError) as ctx_lim:
            self._quote_po(pr, unit_price="10")
        self.assertIn("limit", str(ctx_lim.exception).lower())

        pr2 = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.admin, description="fx", qty="1", sku=self.sku
        )
        self._approve_pr_as_admin(pr2)
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.PROPERTY_FM,
            defaults={"max_amount": Decimal("1000.00"), "is_active": True},
        )
        rfq = ProcurementService.create_rfq_from_pr(pr2, actor=self.admin)
        quote = ProcurementService.add_rfq_quote(
            rfq, supplier_party=self.supplier, unit_price="50", actor=self.admin
        )
        quote.currency = "USD"
        quote.save(update_fields=["currency"])
        with self.assertRaises(DomainError) as ctx_fx:
            ProcurementService.select_rfq_quote_and_create_po(quote, actor=self.fm)
        self.assertIn("valyuta", str(ctx_fx.exception).lower())

    def test_f_manual_blocked_despite_low_value(self):
        pr = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="Manual low",
            lines=[{"description": "pen", "qty": "1"}],
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        self.assertFalse(
            ApprovalRequest.objects.filter(
                workflow_code="procurement.pr",
                status=ApprovalStatus.PENDING,
                entity_id=pr.pk,
            ).exists()
        )

    def test_g_hub_basis_matches_decision_and_idempotent(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="hub", qty="3", sku=self.sku
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        req = ApprovalRequest.objects.get(
            workflow_code="procurement.pr", status=ApprovalStatus.PENDING, entity_id=pr.pk
        )
        self.assertEqual(req.payload.get("amount"), "")
        self.assertEqual(req.payload.get("decision_scope"), "process_only")

        self.client.force_login(self.mgmt)
        page = self.client.get(reverse("erp:approvals"))
        self.assertContains(page, "Məbləğ müəyyən edilməyib")
        self.assertContains(page, pr.code)

        self.client.post(
            reverse("erp:approvals"),
            {"action": "approve", "approval_id": req.pk, "comment": "process ok"},
        )
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.APPROVED)
        # Repeated decide
        again = self.client.post(
            reverse("erp:approvals"),
            {"action": "reject", "approval_id": req.pk},
        )
        self.assertEqual(again.status_code, 404)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.APPROVED)

    def test_h_multiple_pos_respect_role_limit_cumulative(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="multi", qty="2", sku=self.sku
        )
        self._approve_pr_as_admin(pr)
        line_id = pr.lines.get().pk
        # process_only approval — cumulative role limit still applies to known quotes.
        po1 = ProcurementService.create_po_from_pr(
            pr,
            supplier_party=self.supplier,
            actor=self.fm,
            unit_price="700",
            line_qtys={line_id: "1"},
        )
        self.assertEqual(ProcurementService.assess_po_amount(po1).amount, Decimal("700.00"))
        with self.assertRaises(DomainError) as ctx:
            ProcurementService.create_po_from_pr(
                pr,
                supplier_party=self.supplier,
                actor=self.fm,
                unit_price="700",
                line_qtys={line_id: "1"},
            )
        self.assertIn("öhdəlik sorğusu", str(ctx.exception))
        self.assertEqual(pr.purchase_orders.count(), 1)

        # Admin may still convert (override); documents open spending until Finance sets ceiling policy.
        po2 = ProcurementService.create_po_from_pr(
            pr,
            supplier_party=self.supplier,
            actor=self.admin,
            unit_price="700",
            line_qtys={line_id: "1"},
        )
        self.assertEqual(pr.purchase_orders.count(), 2)
        committed = ProcurementService.pr_committed_amount(pr)
        self.assertEqual(committed.amount, Decimal("1400.00"))

    def test_i_document_and_goods_receipt_paths_untouched_smoke(self):
        from apps.documents.models import DocumentSensitivity, DocumentType, DOCUMENT_TYPE_OTHER
        from apps.documents.services import DocumentService
        from django.core.files.uploadedfile import SimpleUploadedFile

        dtype, _ = DocumentType.objects.get_or_create(
            code=DOCUMENT_TYPE_OTHER,
            defaults={"name": "Digər", "requires_approval": True},
        )
        dtype.requires_approval = True
        dtype.default_sensitivity = DocumentSensitivity.CONFIDENTIAL
        dtype.save()
        doc = DocumentService.upload_new(
            title="MON Doc",
            uploaded_file=SimpleUploadedFile("m.pdf", b"%PDF-1.4", content_type="application/pdf"),
            document_type=dtype,
            created_by=self.fm,
        )
        req = DocumentService.submit_for_approval(doc, actor=self.fm)
        DocumentService.decide_approval(req, actor=self.mgmt, approved=True, comment="ok")
        req.refresh_from_db()
        self.assertEqual(req.status, ApprovalStatus.APPROVED)
