"""Line-level RFQ sourcing — invitations, coverage states, whole-line awards, multi-PO."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
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

    def test_partial_qty_visible_cannot_award_whole_line(self):
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
                    "qty": "6",  # remaining is 10
                }
            ],
        )
        ql = q.lines.get(pr_line=lines[0])
        cmp = ProcurementService.build_line_comparison(rfq)
        cell = next(r for r in cmp["rows"] if r.pr_line.pk == lines[0].pk).cells[
            self.sup_b.pk
        ]
        self.assertEqual(cell.coverage, ComparisonCoverage.QUOTED)
        self.assertFalse(cell.award_eligible)
        with self.assertRaises(DomainError) as ctx:
            ProcurementService.award_pr_lines(
                pr,
                [{"pr_line_id": lines[0].pk, "quote_line_id": ql.pk}],
                actor=self.fm,
            )
        self.assertIn("qismən", str(ctx.exception).lower())

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
        # Change quote terms → new award fingerprint
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

    def test_line_split_blocked_and_legacy_header_coherent(self):
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
                    "unit_price": "3",
                    "qty": "10",
                }
            ],
        )
        ql = qb.lines.get()
        with self.assertRaises(DomainError) as ctx:
            ProcurementService.award_pr_lines(
                pr,
                [{"pr_line_id": lines[0].pk, "quote_line_id": ql.pk, "qty": "4"}],
                actor=self.fm,
            )
        self.assertIn("bölünməsi", str(ctx.exception).lower())

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
        ProcurementService.award_pr_lines(
            pr,
            [{"pr_line_id": lines[0].pk, "quote_line_id": ql.pk}],
            actor=self.fm,
        )
        header_q = ProcurementService.add_rfq_quote(
            rfq, supplier_party=self.sup_a, unit_price="1", actor=self.fm
        )
        # Management commitment is checked first; once approved, awards still block header select.
        with self.assertRaises(DomainError):
            ProcurementService.select_rfq_quote_and_create_po(header_q, actor=self.admin)
        approve_pending_commitment(pr, mgmt=self.mgmt)
        with self.assertRaises(DomainError) as ctx2:
            ProcurementService.select_rfq_quote_and_create_po(header_q, actor=self.admin)
        self.assertIn("mükafat", str(ctx2.exception).lower())

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
