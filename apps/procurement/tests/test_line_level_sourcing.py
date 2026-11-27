"""Line-level RFQ sourcing — invitations, coverage states, whole-line awards, multi-PO."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.parties.models import Party, PartyRole, PartyRoleCode
from apps.procurement.models import (
    ComparisonCoverage,
    POStatus,
    PRLineAward,
    PRStatus,
    PurchaseApprovalLimit,
    QuoteLineResponseStatus,
    RFQDispatchChannel,
    RFQInvitation,
)
from apps.procurement.services import (
    WF_PROCUREMENT_COMMITMENT,
    ProcurementService,
)
from apps.procurement.tests.support import (
    approve_all_pending_commitments,
    approve_pending_commitment,
    approve_pr_via_management,
    issue_quote_po,
)
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.warehouse.models import SKU, Stock, Warehouse
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


@override_settings(PROCUREMENT_QUOTE_VAT_RATE="0.18")
class LineLevelSourcingAcceptanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.client = Client()
        self.fm = User.objects.create_user(
            username="lls-fm",
            email="lls-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(self.fm, "supply.head")
        self.mgmt = User.objects.create_user(
            username="lls-mgmt",
            email="lls-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="lls-admin",
            email="lls-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("5000.00"), "is_active": True},
        )
        self.wh = Warehouse.objects.create(code="LLSWH", name="LLS WH")
        self.skus = []
        for i in range(1, 11):
            sku = SKU.objects.create(
                code=f"LLS-{i:02d}", name=f"Item {i}", unit="pcs", reorder_level=1
            )
            Stock.objects.create(sku=sku, warehouse=self.wh, quantity=Decimal("0"))
            self.skus.append(sku)
        self.sup_a = Party.objects.create(legal_name="LLS Supplier A")
        self.sup_b = Party.objects.create(legal_name="LLS Supplier B")
        self.sup_c = Party.objects.create(legal_name="LLS Supplier C")
        for p in (self.sup_a, self.sup_b, self.sup_c):
            PartyRole.objects.get_or_create(party=p, role=PartyRoleCode.SUPPLIER)

    def _ten_line_pr(self):
        lines = [
            {
                "sku_id": sku.pk,
                "description": sku.name,
                "qty": "10",
                "unit": "pcs",
            }
            for sku in self.skus
        ]
        pr = ProcurementService.create_manual_pr(
            actor=self.fm, title="LLS 10-line", lines=lines
        )
        approve_pr_via_management(pr, actor=self.admin)
        return pr

    def _invite_scopes(self, rfq, pr):
        lines = list(pr.lines.order_by("id"))
        inv_a = ProcurementService.invite_supplier_to_rfq(
            rfq,
            supplier_party=self.sup_a,
            line_specs=[{"pr_line_id": ln.pk} for ln in lines],
            actor=self.fm,
            dispatch_channel=RFQDispatchChannel.EMAIL,
            dispatch_ref="outbox-A-1",
            mark_dispatched=True,
        )
        inv_b = ProcurementService.invite_supplier_to_rfq(
            rfq,
            supplier_party=self.sup_b,
            line_specs=[{"pr_line_id": ln.pk} for ln in lines[:4]],
            actor=self.fm,
            dispatch_channel=RFQDispatchChannel.MANUAL,
            dispatch_ref="hand-B-1",
            mark_dispatched=True,
        )
        inv_c = ProcurementService.invite_supplier_to_rfq(
            rfq,
            supplier_party=self.sup_c,
            line_specs=[{"pr_line_id": ln.pk} for ln in lines[4:]],
            actor=self.fm,
            dispatch_channel=RFQDispatchChannel.MANUAL,
            dispatch_ref="hand-C-1",
            mark_dispatched=True,
        )
        return inv_a, inv_b, inv_c, lines

    def test_invitation_scopes_and_request_text(self):
        pr = self._ten_line_pr()
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        inv_a, inv_b, inv_c, lines = self._invite_scopes(rfq, pr)
        self.assertTrue(inv_a.is_dispatched)
        self.assertEqual(inv_a.lines.count(), 10)
        self.assertEqual(inv_b.lines.count(), 4)
        self.assertEqual(inv_c.lines.count(), 6)
        self.assertIn(rfq.code, inv_a.request_text)
        self.assertIn(str(lines[0].pk), inv_b.request_text)
        # Draft alone is not dispatched
        draft = ProcurementService.invite_supplier_to_rfq(
            rfq,
            supplier_party=self.sup_a,
            line_specs=[{"pr_line_id": lines[0].pk}],
            actor=self.fm,
            dispatch_channel=RFQDispatchChannel.DRAFT,
            mark_dispatched=False,
        )
        self.assertFalse(draft.is_dispatched)
        inv_a.refresh_from_db()
        self.assertFalse(inv_a.is_active)  # superseded
        self.assertTrue(
            RFQInvitation.objects.filter(pk=inv_a.pk, dispatched_at__isnull=False).exists()
        )

    def test_coverage_states_zero_unanswered_not_invited(self):
        pr = self._ten_line_pr()
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        _, inv_b, inv_c, lines = self._invite_scopes(rfq, pr)
        # B: line0 unanswered, line1 zero quoted, lines 2-3 quoted
        ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_b,
            actor=self.fm,
            line_responses=[
                {"pr_line_id": lines[0].pk, "response_status": "unanswered"},
                {
                    "pr_line_id": lines[1].pk,
                    "response_status": "quoted",
                    "unit_price": "0",
                    "qty": "10",
                },
                {
                    "pr_line_id": lines[2].pk,
                    "response_status": "quoted",
                    "unit_price": "5",
                    "qty": "10",
                },
                {
                    "pr_line_id": lines[3].pk,
                    "response_status": "quoted",
                    "unit_price": "5",
                    "qty": "10",
                },
            ],
        )
        # C quotes line 4 only — line 5+ invited unanswered; B lines NOT_INVITED for C
        ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_c,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": lines[4].pk,
                    "response_status": "quoted",
                    "unit_price": "8",
                    "qty": "10",
                },
            ],
        )
        cmp = ProcurementService.build_line_comparison(rfq)
        by_line = {r.pr_line.pk: r for r in cmp["rows"]}
        self.assertEqual(
            by_line[lines[0].pk].cells[self.sup_b.pk].coverage,
            ComparisonCoverage.INVITED_UNANSWERED,
        )
        self.assertEqual(
            by_line[lines[1].pk].cells[self.sup_b.pk].coverage,
            ComparisonCoverage.QUOTED,
        )
        self.assertEqual(
            by_line[lines[1].pk].cells[self.sup_b.pk].quote_line.unit_price,
            Decimal("0.00"),
        )
        self.assertEqual(
            by_line[lines[0].pk].cells[self.sup_c.pk].coverage,
            ComparisonCoverage.NOT_INVITED,
        )
        self.assertEqual(
            by_line[lines[5].pk].cells[self.sup_c.pk].coverage,
            ComparisonCoverage.INVITED_UNANSWERED,
        )
        # Out of scope rejected
        with self.assertRaises(DomainError) as ctx:
            ProcurementService.add_rfq_quote_lines(
                rfq,
                supplier_party=self.sup_b,
                actor=self.fm,
                line_responses=[
                    {
                        "pr_line_id": lines[5].pk,
                        "response_status": "quoted",
                        "unit_price": "1",
                    }
                ],
            )
        self.assertIn("əhatə", str(ctx.exception).lower())

        self.client.force_login(self.fm)
        r = self.client.get(reverse("erp:procurement_rfq_detail", kwargs={"code": rfq.code}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Dəvət olunmayıb")
        self.assertContains(r, "Cavabsız")

    def test_partial_quote_awardable_for_portion(self):
        pr = self._ten_line_pr()
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        _, _, _, lines = self._invite_scopes(rfq, pr)
        q = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_b,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": lines[0].pk,
                    "response_status": "quoted",
                    "unit_price": "3",
                    "qty": "6",
                }
            ],
        )
        ql = q.lines.get(pr_line=lines[0])
        cmp = ProcurementService.build_line_comparison(rfq)
        cell = next(r for r in cmp["rows"] if r.pr_line.pk == lines[0].pk).cells[
            self.sup_b.pk
        ]
        self.assertEqual(cell.coverage, ComparisonCoverage.QUOTED)
        self.assertTrue(cell.award_eligible)
        awards = ProcurementService.award_pr_lines(
            pr,
            [{"pr_line_id": lines[0].pk, "quote_line_id": ql.pk, "qty": "6"}],
            actor=self.fm,
        )
        self.assertEqual(awards[0].qty, Decimal("6.000"))
        self.assertEqual(
            ProcurementService.pr_line_free_to_allocate_qty(lines[0]), Decimal("4.000")
        )
        with self.assertRaises(DomainError):
            ProcurementService.award_pr_lines(
                pr,
                [{"pr_line_id": lines[0].pk, "quote_line_id": ql.pk, "qty": "1"}],
                actor=self.fm,
            )

    def test_b_and_c_awards_trace_to_quote_and_pr_line(self):
        pr = self._ten_line_pr()
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        _, _, _, lines = self._invite_scopes(rfq, pr)
        qb = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_b,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": ln.pk,
                    "response_status": "quoted",
                    "unit_price": "4",
                    "qty": "10",
                }
                for ln in lines[:4]
            ],
        )
        qc = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_c,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": ln.pk,
                    "response_status": "quoted",
                    "unit_price": "5",
                    "qty": "10",
                }
                for ln in lines[4:]
            ],
        )
        selections = [
            {"pr_line_id": ln.pk, "quote_line_id": qb.lines.get(pr_line=ln).pk}
            for ln in lines[:4]
        ] + [
            {"pr_line_id": ln.pk, "quote_line_id": qc.lines.get(pr_line=ln).pk}
            for ln in lines[4:]
        ]
        awards = ProcurementService.award_pr_lines(pr, selections, actor=self.fm)
        self.assertEqual(len(awards), 10)
        # Mandatory Management approval: nothing issues until commitments are approved.
        first = ProcurementService.create_pos_from_awards(pr, actor=self.admin)
        self.assertTrue(all(o.status == "awaiting_financial_approval" for o in first))
        approve_all_pending_commitments(pr)
        outcomes = ProcurementService.create_pos_from_awards(pr, actor=self.admin)
        by_status = {o.supplier_id: o for o in outcomes}
        self.assertEqual(by_status[self.sup_b.pk].status, "issued")
        self.assertEqual(by_status[self.sup_c.pk].status, "issued")
        po_b = by_status[self.sup_b.pk].po
        po_c = by_status[self.sup_c.pk].po
        self.assertEqual(po_b.lines.count(), 4)
        self.assertEqual(po_c.lines.count(), 6)
        for pol in po_b.lines.all():
            self.assertEqual(pol.pr_line_id, pol.quote_line.pr_line_id)
            self.assertEqual(pol.unit_price, Decimal("4.00"))
            self.assertEqual(pol.quote_line.quote_id, qb.pk)
        for pol in po_c.lines.all():
            self.assertEqual(pol.unit_price, Decimal("5.00"))
            self.assertEqual(pol.quote_line.quote_id, qc.pk)

    def test_stale_commitment_after_quote_change(self):
        pr = self._ten_line_pr()
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        _, _, _, lines = self._invite_scopes(rfq, pr)
        # High prices → over FM 5000: 2*10*300*1.18 = 7080
        qc = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_c,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": ln.pk,
                    "response_status": "quoted",
                    "unit_price": "300",
                    "qty": "10",
                }
                for ln in lines[4:6]  # 2 lines only to keep scenario tight
            ],
        )
        awards = ProcurementService.award_pr_lines(
            pr,
            [
                {
                    "pr_line_id": lines[4].pk,
                    "quote_line_id": qc.lines.get(pr_line=lines[4]).pk,
                },
                {
                    "pr_line_id": lines[5].pk,
                    "quote_line_id": qc.lines.get(pr_line=lines[5]).pk,
                },
            ],
            actor=self.fm,
        )
        outcomes = ProcurementService.create_pos_from_awards(
            pr, actor=self.fm, supplier_ids=[self.sup_c.pk]
        )
        self.assertEqual(outcomes[0].status, "awaiting_financial_approval")
        pending = ApprovalRequest.objects.filter(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            status=ApprovalStatus.PENDING,
            entity_id=pr.pk,
        ).latest("id")
        ApprovalService.decide(
            pending, approved=True, decided_by=self.mgmt, comment="ok"
        )
        # Change quote terms → release old awards, re-award with new fingerprint
        qc2 = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_c,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": ln.pk,
                    "response_status": "quoted",
                    "unit_price": "250",
                    "qty": "10",
                }
                for ln in lines[4:6]
            ],
        )
        PRLineAward.objects.filter(
            pr=pr, supplier_party=self.sup_c, is_active=True, po_line__isnull=True
        ).update(is_active=False)
        ProcurementService.award_pr_lines(
            pr,
            [
                {
                    "pr_line_id": lines[4].pk,
                    "quote_line_id": qc2.lines.get(pr_line=lines[4]).pk,
                },
                {
                    "pr_line_id": lines[5].pk,
                    "quote_line_id": qc2.lines.get(pr_line=lines[5]).pk,
                },
            ],
            actor=self.fm,
        )
        outcomes2 = ProcurementService.create_pos_from_awards(
            pr, actor=self.fm, supplier_ids=[self.sup_c.pk]
        )
        self.assertEqual(outcomes2[0].status, "awaiting_financial_approval")
        # Old approved commitment fingerprint must not authorize new terms
        self.assertFalse(
            any(o.status == "issued" for o in outcomes2)
        )

    def test_c_awaiting_does_not_duplicate_b_issued(self):
        pr = self._ten_line_pr()
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        _, _, _, lines = self._invite_scopes(rfq, pr)
        qb = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_b,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": ln.pk,
                    "response_status": "quoted",
                    "unit_price": "2",
                    "qty": "10",
                }
                for ln in lines[:4]
            ],
        )
        # C expensive → escalate
        qc = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_c,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": ln.pk,
                    "response_status": "quoted",
                    "unit_price": "150",
                    "qty": "10",
                }
                for ln in lines[4:]
            ],
        )
        ProcurementService.award_pr_lines(
            pr,
            [
                {"pr_line_id": ln.pk, "quote_line_id": qb.lines.get(pr_line=ln).pk}
                for ln in lines[:4]
            ]
            + [
                {"pr_line_id": ln.pk, "quote_line_id": qc.lines.get(pr_line=ln).pk}
                for ln in lines[4:]
            ],
            actor=self.fm,
        )
        # Mandatory Management approval: first pass escalates both suppliers.
        first = ProcurementService.create_pos_from_awards(pr, actor=self.fm)
        self.assertTrue(all(o.status == "awaiting_financial_approval" for o in first))
        # Management approves only B's commitment (C stays pending).
        pending_b = [
            r
            for r in ApprovalRequest.objects.filter(
                workflow_code=WF_PROCUREMENT_COMMITMENT,
                status=ApprovalStatus.PENDING,
                entity_id=pr.pk,
            )
            if (r.payload or {}).get("supplier_id") == self.sup_b.pk
        ]
        self.assertEqual(len(pending_b), 1)
        ApprovalService.decide(
            pending_b[0], approved=True, decided_by=self.mgmt, comment="B ok"
        )
        outcomes = ProcurementService.create_pos_from_awards(pr, actor=self.fm)
        by_sup = {o.supplier_id: o for o in outcomes}
        self.assertEqual(by_sup[self.sup_b.pk].status, "issued")
        self.assertEqual(by_sup[self.sup_c.pk].status, "awaiting_financial_approval")
        po_b_code = by_sup[self.sup_b.pk].po.code
        # Retry must not duplicate B
        outcomes2 = ProcurementService.create_pos_from_awards(pr, actor=self.fm)
        by_sup2 = {o.supplier_id: o for o in outcomes2 if o.supplier_id}
        self.assertNotIn(self.sup_b.pk, by_sup2)  # already linked → filtered out
        self.assertEqual(by_sup2[self.sup_c.pk].status, "awaiting_financial_approval")
        pending = ApprovalRequest.objects.filter(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            status=ApprovalStatus.PENDING,
            entity_id=pr.pk,
        ).latest("id")
        ApprovalService.decide(
            pending, approved=True, decided_by=self.mgmt, comment="C ok"
        )
        outcomes3 = ProcurementService.create_pos_from_awards(pr, actor=self.fm)
        by_sup3 = {o.supplier_id: o for o in outcomes3}
        self.assertEqual(by_sup3[self.sup_c.pk].status, "issued")
        self.assertEqual(
            PRLineAward.objects.filter(
                pr=pr, supplier_party=self.sup_b, is_active=True
            )
            .exclude(po_line=None)
            .count(),
            4,
        )
        # B still single PO
        from apps.procurement.models import PurchaseOrder

        self.assertEqual(
            PurchaseOrder.objects.filter(pr=pr, supplier_party=self.sup_b).count(), 1
        )
        self.assertEqual(
            PurchaseOrder.objects.get(pr=pr, supplier_party=self.sup_b).code, po_b_code
        )

    def test_split_6_plus_4_approve_issue_receive(self):
        """Decision 03 worked example: request 10, A=6 B=4, approve A only, then B; receive 2+4 and 4."""
        import uuid

        pr = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="Filters 10",
            lines=[
                {
                    "sku_id": self.skus[0].pk,
                    "description": "Filter",
                    "qty": "10",
                    "unit": "pcs",
                }
            ],
        )
        approve_pr_via_management(pr, actor=self.admin)
        line = pr.lines.get()
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        for sup in (self.sup_a, self.sup_b):
            ProcurementService.invite_supplier_to_rfq(
                rfq,
                supplier_party=sup,
                line_specs=[{"pr_line_id": line.pk}],
                actor=self.fm,
                dispatch_channel=RFQDispatchChannel.EMAIL,
                dispatch_ref=f"split-{sup.pk}",
                mark_dispatched=True,
            )
        qa = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_a,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": line.pk,
                    "response_status": "quoted",
                    "unit_price": "10",
                    "qty": "6",
                }
            ],
        )
        qb = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_b,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": line.pk,
                    "response_status": "quoted",
                    "unit_price": "11",
                    "qty": "4",
                }
            ],
        )
        awards = ProcurementService.award_pr_lines(
            pr,
            [
                {
                    "pr_line_id": line.pk,
                    "quote_line_id": qa.lines.get().pk,
                    "qty": "6",
                    "reason": "availability",
                },
                {
                    "pr_line_id": line.pk,
                    "quote_line_id": qb.lines.get().pk,
                    "qty": "4",
                    "reason": "quality",
                },
            ],
            actor=self.fm,
        )
        self.assertEqual(len(awards), 2)
        self.assertEqual(ProcurementService.pr_line_ordered_qty(line), Decimal("0"))
        self.assertEqual(
            ProcurementService.pr_line_awarded_unissued_qty(line), Decimal("10.000")
        )
        self.assertEqual(
            ProcurementService.pr_line_free_to_allocate_qty(line), Decimal("0")
        )
        with self.assertRaises(DomainError):
            ProcurementService.award_pr_lines(
                pr,
                [
                    {
                        "pr_line_id": line.pk,
                        "quote_line_id": qa.lines.get().pk,
                        "qty": "1",
                    }
                ],
                actor=self.fm,
            )

        # Approve A only → issue A
        first = ProcurementService.create_pos_from_awards(pr, actor=self.fm)
        self.assertTrue(all(o.status == "awaiting_financial_approval" for o in first))
        pending_a = ApprovalRequest.objects.filter(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            status=ApprovalStatus.PENDING,
            entity_id=pr.pk,
        )
        for req in pending_a:
            payload = req.payload or {}
            if payload.get("supplier_id") == self.sup_a.pk:
                ApprovalService.decide(
                    req, approved=True, decided_by=self.mgmt, comment="A only"
                )
        issued = ProcurementService.create_pos_from_awards(
            pr, actor=self.fm, supplier_ids=[self.sup_a.pk]
        )
        self.assertEqual(issued[0].status, "issued")
        line.refresh_from_db()
        self.assertEqual(ProcurementService.pr_line_ordered_qty(line), Decimal("6.000"))
        self.assertEqual(
            ProcurementService.pr_line_awarded_unissued_qty(line), Decimal("4.000")
        )
        self.assertEqual(
            ProcurementService.pr_line_free_to_allocate_qty(line), Decimal("0")
        )
        self.assertEqual(ProcurementService.pr_line_received_qty(line), Decimal("0"))

        # Direct PO cannot steal B's reserved 4
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr,
                supplier_party=self.sup_c,
                actor=self.admin,
                line_qtys={line.pk: "1"},
            )

        # Approve + issue B
        approve_all_pending_commitments(pr, mgmt=self.mgmt)
        issued_b = ProcurementService.create_pos_from_awards(
            pr, actor=self.fm, supplier_ids=[self.sup_b.pk]
        )
        self.assertEqual(issued_b[0].status, "issued")
        self.assertEqual(ProcurementService.pr_line_ordered_qty(line), Decimal("10.000"))
        self.assertEqual(
            ProcurementService.pr_line_awarded_unissued_qty(line), Decimal("0")
        )

        po_a = issued[0].po
        po_b = issued_b[0].po
        pol_a = po_a.lines.get()
        pol_b = po_b.lines.get()
        key1 = uuid.uuid4().hex
        ProcurementService.receive_po(
            po_a,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={pol_a.pk: "2"},
            operation_key=key1,
            receive_mode="partial",
        )
        # Replay same key — no double stock
        ProcurementService.receive_po(
            po_a,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={pol_a.pk: "2"},
            operation_key=key1,
            receive_mode="partial",
        )
        ProcurementService.receive_po(
            po_a,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={pol_a.pk: "4"},
            operation_key=uuid.uuid4().hex,
            receive_mode="partial",
        )
        ProcurementService.receive_po(
            po_b,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={pol_b.pk: "4"},
            operation_key=uuid.uuid4().hex,
            receive_mode="partial",
        )
        self.assertEqual(ProcurementService.pr_line_ordered_qty(line), Decimal("10.000"))
        self.assertEqual(ProcurementService.pr_line_received_qty(line), Decimal("10.000"))
        progress = ProcurementService.pr_qty_progress(pr)[0]
        self.assertEqual(progress["outstanding_receipt"], Decimal("0"))

        # Legacy header path still works on a fresh PR without line awards
        pr2 = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="LLS header",
            lines=[
                {
                    "sku_id": self.skus[0].pk,
                    "description": "H",
                    "qty": "5",
                    "unit": "pcs",
                }
            ],
        )
        approve_pr_via_management(pr2, actor=self.admin)
        rfq2 = ProcurementService.create_rfq_from_pr(pr2, actor=self.fm)
        q = ProcurementService.add_rfq_quote(
            rfq2, supplier_party=self.sup_a, unit_price="10", actor=self.fm
        )
        assessed = ProcurementService.assess_quote_amount(q, pr2)
        self.assertEqual(assessed.amount, Decimal("50.00"))
        po = issue_quote_po(q, actor=self.admin)
        self.assertEqual(po.status, POStatus.SENT)

        # With active awards, header select blocked
        pr3 = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="Award vs header",
            lines=[
                {
                    "sku_id": self.skus[1].pk,
                    "description": "Block header",
                    "qty": "3",
                    "unit": "pcs",
                }
            ],
        )
        approve_pr_via_management(pr3, actor=self.admin)
        line3 = pr3.lines.get()
        rfq3 = ProcurementService.create_rfq_from_pr(pr3, actor=self.fm)
        ProcurementService.invite_supplier_to_rfq(
            rfq3,
            supplier_party=self.sup_b,
            line_specs=[{"pr_line_id": line3.pk}],
            actor=self.fm,
            dispatch_channel=RFQDispatchChannel.EMAIL,
            dispatch_ref="header-block-1",
            mark_dispatched=True,
        )
        q3 = ProcurementService.add_rfq_quote_lines(
            rfq3,
            supplier_party=self.sup_b,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": line3.pk,
                    "response_status": "quoted",
                    "unit_price": "2",
                    "qty": "3",
                }
            ],
        )
        ProcurementService.award_pr_lines(
            pr3,
            [{"pr_line_id": line3.pk, "quote_line_id": q3.lines.get().pk}],
            actor=self.fm,
        )
        header_q = ProcurementService.add_rfq_quote(
            rfq3, supplier_party=self.sup_a, unit_price="1", actor=self.fm
        )
        with self.assertRaises(DomainError):
            ProcurementService.select_rfq_quote_and_create_po(header_q, actor=self.admin)
        # Direct PO also cannot consume reserved award qty
        with self.assertRaises(DomainError) as ctx_free:
            ProcurementService.create_po_from_pr(
                pr3,
                supplier_party=self.sup_a,
                actor=self.admin,
                line_qtys={line3.pk: "1"},
            )
        self.assertTrue(
            "sərbəst" in str(ctx_free.exception).lower()
            or "mükafat" in str(ctx_free.exception).lower()
            or "qalan" in str(ctx_free.exception).lower()
        )

        # Release unused allocation preserves history
        award_hist = PRLineAward.objects.get(pr=pr3, is_active=True, po_line__isnull=True)
        award_hist.is_active = False
        award_hist.save(update_fields=["is_active"])
        self.assertTrue(PRLineAward.objects.filter(pk=award_hist.pk, is_active=False).exists())
        self.assertEqual(
            ProcurementService.pr_line_free_to_allocate_qty(line3), Decimal("3.000")
        )

    def test_dispatch_requires_evidence(self):
        pr = self._ten_line_pr()
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        line = pr.lines.order_by("id").first()
        with self.assertRaises(DomainError):
            ProcurementService.invite_supplier_to_rfq(
                rfq,
                supplier_party=self.sup_a,
                line_specs=[{"pr_line_id": line.pk}],
                actor=self.fm,
                dispatch_channel=RFQDispatchChannel.DRAFT,
                mark_dispatched=True,
            )

    def test_receipt_traceable_after_award_po(self):
        pr = self._ten_line_pr()
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        _, _, _, lines = self._invite_scopes(rfq, pr)
        qb = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_b,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": lines[0].pk,
                    "response_status": "quoted",
                    "unit_price": "4",
                    "qty": "10",
                }
            ],
        )
        ProcurementService.award_pr_lines(
            pr,
            [
                {
                    "pr_line_id": lines[0].pk,
                    "quote_line_id": qb.lines.get(pr_line=lines[0]).pk,
                }
            ],
            actor=self.fm,
        )
        first = ProcurementService.create_pos_from_awards(
            pr, actor=self.admin, supplier_ids=[self.sup_b.pk]
        )
        self.assertEqual(first[0].status, "awaiting_financial_approval")
        approve_all_pending_commitments(pr)
        outcomes = ProcurementService.create_pos_from_awards(
            pr, actor=self.admin, supplier_ids=[self.sup_b.pk]
        )
        po = outcomes[0].po
        pol = po.lines.get()
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={pol.pk: "4"},
        )
        pol.refresh_from_db()
        self.assertEqual(pol.received_qty, Decimal("4"))
        self.assertEqual(pol.pr_line_id, lines[0].pk)
        self.assertEqual(pol.quote_line_id, qb.lines.get(pr_line=lines[0]).pk)
        progress = ProcurementService.pr_qty_progress(pr)
        row0 = next(r for r in progress if r["line"].pk == lines[0].pk)
        self.assertEqual(row0["ordered"], Decimal("10"))
        self.assertEqual(row0["received"], Decimal("4"))


@override_settings(PROCUREMENT_QUOTE_VAT_RATE="0.18")
class LineSplitConcurrencyTests(TransactionTestCase):
    """Concurrent direct PO vs RFQ allocation on the same remainder."""

    def setUp(self):
        seed_rbac_catalog()
        self.fm = User.objects.create_user(
            username="lls-conc-fm",
            email="lls-conc-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(self.fm, "supply.head")
        self.admin = User.objects.create_user(
            username="lls-conc-admin",
            email="lls-conc-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("5000.00"), "is_active": True},
        )
        self.wh = Warehouse.objects.create(code="LLSCWH", name="LLS Conc WH")
        self.sku = SKU.objects.create(code="LLS-C1", name="Conc Item", unit="pcs")
        Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("0"))
        self.sup_a = Party.objects.create(legal_name="Conc A")
        self.sup_b = Party.objects.create(legal_name="Conc B")
        for p in (self.sup_a, self.sup_b):
            PartyRole.objects.get_or_create(party=p, role=PartyRoleCode.SUPPLIER)

    def test_concurrent_award_and_direct_po_serialize(self):
        import threading

        pr = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="Conc split",
            lines=[
                {
                    "sku_id": self.sku.pk,
                    "description": "Conc",
                    "qty": "10",
                    "unit": "pcs",
                }
            ],
        )
        approve_pr_via_management(pr, actor=self.admin)
        line = pr.lines.get()
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        ProcurementService.invite_supplier_to_rfq(
            rfq,
            supplier_party=self.sup_a,
            line_specs=[{"pr_line_id": line.pk}],
            actor=self.fm,
            dispatch_channel=RFQDispatchChannel.EMAIL,
            dispatch_ref="conc-outbox-1",
            mark_dispatched=True,
        )
        qa = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_a,
            actor=self.fm,
            line_responses=[
                {
                    "pr_line_id": line.pk,
                    "response_status": "quoted",
                    "unit_price": "5",
                    "qty": "10",
                }
            ],
        )
        ql_id = qa.lines.get().pk
        errors: list[str] = []
        results: list[str] = []

        def award_half():
            try:
                ProcurementService.award_pr_lines(
                    pr,
                    [{"pr_line_id": line.pk, "quote_line_id": ql_id, "qty": "6"}],
                    actor=self.fm,
                )
                results.append("award")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"award:{exc}")

        def direct_po():
            try:
                from apps.procurement.tests.support import issue_priced_po

                issue_priced_po(
                    pr,
                    supplier=self.sup_b,
                    unit_price="5",
                    actor=self.admin,
                    line_qtys={line.pk: "6"},
                )
                results.append("po")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"po:{exc}")

        t1 = threading.Thread(target=award_half)
        t2 = threading.Thread(target=direct_po)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # Exactly one path may take 6 from free=10; the other must fail or take remainder ≤4.
        ordered = ProcurementService.pr_line_ordered_qty(line)
        allocated = ProcurementService.pr_line_awarded_unissued_qty(line)
        self.assertLessEqual(ordered + allocated, Decimal("10.000"))
        self.assertGreaterEqual(ordered + allocated, Decimal("6.000"))
        self.assertTrue(results, msg=f"no success; errors={errors}")
