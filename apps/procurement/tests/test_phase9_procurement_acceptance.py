"""Product Delivery Phase 9 — procurement acceptance + qty/RFQ boundaries."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.parties.models import Party, PartyRole, PartyRoleCode
from apps.procurement.models import POStatus, PRStatus, PurchaseApprovalLimit
from apps.procurement.services import ProcurementService
from apps.procurement.tests.support import (
    approve_pr_via_management,
    issue_quote_po,
)
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.warehouse.models import SKU, Stock, StockMovement, StockMovementType, Warehouse

User = get_user_model()


class Phase9ProcurementAcceptanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.client = Client()
        self.fm = User.objects.create_user(
            username="p9-fm",
            email="p9-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(self.fm, "supply.head")
        self.mgmt = User.objects.create_user(
            username="p9-mgmt",
            email="p9-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="p9-admin",
            email="p9-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("5000.00"), "is_active": True},
        )
        self.wh = Warehouse.objects.create(code="P9WH", name="Phase9 WH")
        self.sku_a = SKU.objects.create(code="P9-FILTER", name="Filter", unit="pcs", reorder_level=2)
        self.sku_b = SKU.objects.create(code="P9-OIL", name="Oil", unit="L", reorder_level=1)
        Stock.objects.create(sku=self.sku_a, warehouse=self.wh, quantity=Decimal("1"))
        Stock.objects.create(sku=self.sku_b, warehouse=self.wh, quantity=Decimal("2"))
        self.sup_a = Party.objects.create(legal_name="P9 Alpha Supply")
        self.sup_b = Party.objects.create(legal_name="P9 Beta Supply")
        PartyRole.objects.get_or_create(party=self.sup_a, role=PartyRoleCode.SUPPLIER)
        PartyRole.objects.get_or_create(party=self.sup_b, role=PartyRoleCode.SUPPLIER)

    def test_empty_quote_price_not_zero(self):
        pr = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="P9 empty price",
            lines=[{"sku_id": self.sku_a.pk, "description": "Filter", "qty": "10", "unit": "pcs"}],
        )
        approve_pr_via_management(pr, actor=self.admin)
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        with self.assertRaises(DomainError) as ctx:
            ProcurementService.add_rfq_quote(
                rfq, supplier_party=self.sup_a, unit_price="", actor=self.fm
            )
        self.assertIn("sıfır", str(ctx.exception).lower())

    def test_qty_split_orders_and_block_over_order(self):
        pr = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="P9 qty 10",
            lines=[{"sku_id": self.sku_a.pk, "description": "Filter", "qty": "10", "unit": "pcs"}],
        )
        approve_pr_via_management(pr, actor=self.admin)
        line_id = pr.lines.get().pk
        # Qty-split accounting is independent of money: use unpriced (draft) tranches.
        # Priced issue needs a Management commitment per tranche and is covered elsewhere.
        po1 = ProcurementService.create_po_from_pr(
            pr,
            supplier_party=self.sup_a,
            actor=self.fm,
            line_qtys={line_id: "6"},
        )
        self.assertEqual(po1.lines.get().qty, Decimal("6"))
        progress = ProcurementService.pr_qty_progress(pr)
        self.assertEqual(progress[0]["ordered"], Decimal("6"))
        self.assertEqual(progress[0]["outstanding_order"], Decimal("4"))
        po2 = ProcurementService.create_po_from_pr(
            pr,
            supplier_party=self.sup_b,
            actor=self.fm,
            line_qtys={line_id: "4"},
        )
        self.assertEqual(po2.lines.get().qty, Decimal("4"))
        progress = ProcurementService.pr_qty_progress(pr)
        self.assertEqual(progress[0]["ordered"], Decimal("10"))
        self.assertEqual(progress[0]["outstanding_order"], Decimal("0"))
        with self.assertRaises(DomainError) as ctx:
            ProcurementService.create_po_from_pr(
                pr,
                supplier_party=self.sup_a,
                actor=self.fm,
                line_qtys={line_id: "1"},
            )
        msg = str(ctx.exception).lower()
        self.assertTrue(
            "sərbəst" in msg or "qalan" in msg,
            msg=f"expected free/remaining qty block, got: {ctx.exception}",
        )
    def test_two_supplier_comparison_totals(self):
        """Scenario P9-A (comparison only): 10 filters + 5 L oil — not the receipt journey PR."""
        pr = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="P9 compare",
            lines=[
                {"sku_id": self.sku_a.pk, "description": "Filter", "qty": "10", "unit": "pcs"},
                {"sku_id": self.sku_b.pk, "description": "Oil", "qty": "5", "unit": "L"},
            ],
        )
        approve_pr_via_management(pr, actor=self.admin)
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        q_hi = ProcurementService.add_rfq_quote(
            rfq, supplier_party=self.sup_a, unit_price="20", actor=self.fm
        )
        q_lo = ProcurementService.add_rfq_quote(
            rfq, supplier_party=self.sup_b, unit_price="15", actor=self.fm
        )
        # Single unit price × (10+5) remaining
        a_hi = ProcurementService.assess_quote_amount(q_hi, pr)
        a_lo = ProcurementService.assess_quote_amount(q_lo, pr)
        self.assertEqual(a_hi.amount, Decimal("300.00"))  # 20*15
        self.assertEqual(a_lo.amount, Decimal("225.00"))  # 15*15
        self.assertEqual(a_lo.basis, "rfq_quote_unit_price_x_pr_qty")
        self.client.force_login(self.fm)
        r = self.client.get(reverse("erp:procurement_rfq_detail", kwargs={"code": rfq.code}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "225.00")
        self.assertContains(r, "ən ucuz")
        self.assertEqual(r.context["lowest_quote_id"], q_lo.pk)

    def test_operator_journey_http_two_receipts_and_replay(self):
        """Scenario P9-B (e2e receive): 10 filters + 4 L oil — separate PR from P9-A compare."""
        self.client.force_login(self.fm)
        # 1–2 create + approve PR (admin approve)
        pr = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="P9 journey",
            lines=[
                {"sku_id": self.sku_a.pk, "description": "Filter", "qty": "10", "unit": "pcs"},
                {"sku_id": self.sku_b.pk, "description": "Oil", "qty": "4", "unit": "L"},
            ],
        )
        approve_pr_via_management(pr, actor=self.admin)
        self.assertEqual(pr.status, PRStatus.APPROVED)

        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.fm)
        ProcurementService.add_rfq_quote(
            rfq, supplier_party=self.sup_a, unit_price="12", actor=self.fm
        )
        q_win = ProcurementService.add_rfq_quote(
            rfq, supplier_party=self.sup_b, unit_price="10", actor=self.fm
        )
        assessed = ProcurementService.assess_quote_amount(q_win, pr)
        # 10*(10+4)=140
        self.assertEqual(assessed.amount, Decimal("140.00"))

        po = issue_quote_po(q_win, actor=self.fm)
        self.assertEqual(po.supplier_party_id, self.sup_b.pk)
        self.assertEqual(po.lines.count(), 2)
        self.assertEqual(sum(ln.qty for ln in po.lines.all()), Decimal("14"))

        # Management can view PR
        self.client.force_login(self.mgmt)
        r = self.client.get(reverse("erp:procurement_pr_detail", kwargs={"code": pr.code}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "10")
        # Management cannot create PO
        r = self.client.post(
            reverse("erp:procurement_pr_detail", kwargs={"code": pr.code}),
            {"action": "create_po", "supplier_party_id": self.sup_a.pk},
        )
        self.assertIn(r.status_code, (302, 403))
        self.assertEqual(pr.purchase_orders.count(), 1)

        # Warehouse receives in two deliveries
        self.client.force_login(self.fm)
        line_a = po.lines.get(sku=self.sku_a)
        line_b = po.lines.get(sku=self.sku_b)
        before_a = Stock.objects.get(sku=self.sku_a, warehouse=self.wh).quantity
        before_b = Stock.objects.get(sku=self.sku_b, warehouse=self.wh).quantity

        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.fm,
            receive_mode="partial",
            line_qtys={line_a.pk: "6", line_b.pk: "2"},
            operation_key="p9-recv-1",
        )
        # Replay same key — no extra stock
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.fm,
            receive_mode="partial",
            line_qtys={line_a.pk: "6", line_b.pk: "2"},
            operation_key="p9-recv-1",
        )
        mid_a = Stock.objects.get(sku=self.sku_a, warehouse=self.wh).quantity
        mid_b = Stock.objects.get(sku=self.sku_b, warehouse=self.wh).quantity
        self.assertEqual(mid_a, before_a + Decimal("6"))
        self.assertEqual(mid_b, before_b + Decimal("2"))

        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.fm,
            receive_mode="partial",
            line_qtys={line_a.pk: "4", line_b.pk: "2"},
            operation_key="p9-recv-2",
        )
        po.refresh_from_db()
        self.assertEqual(po.status, POStatus.RECEIVED)
        end_a = Stock.objects.get(sku=self.sku_a, warehouse=self.wh).quantity
        end_b = Stock.objects.get(sku=self.sku_b, warehouse=self.wh).quantity
        self.assertEqual(end_a, before_a + Decimal("10"))
        self.assertEqual(end_b, before_b + Decimal("4"))

        progress = ProcurementService.pr_qty_progress(pr)
        by_sku = {row["line"].sku_id: row for row in progress}
        self.assertEqual(by_sku[self.sku_a.pk]["requested"], Decimal("10"))
        self.assertEqual(by_sku[self.sku_a.pk]["ordered"], Decimal("10"))
        self.assertEqual(by_sku[self.sku_a.pk]["received"], Decimal("10"))
        self.assertEqual(by_sku[self.sku_a.pk]["outstanding_order"], Decimal("0"))
        self.assertEqual(by_sku[self.sku_b.pk]["received"], Decimal("4"))

        receipts = StockMovement.objects.filter(
            warehouse=self.wh,
            movement_type=StockMovementType.RECEIPT,
            reference=po.code,
        )
        # Two deliveries × two SKUs = 4 movements (replay must not add)
        self.assertEqual(receipts.count(), 4)

        self.client.force_login(self.fm)
        r = self.client.get(reverse("erp:procurement_pr_detail", kwargs={"code": pr.code}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Qalan sifariş")
