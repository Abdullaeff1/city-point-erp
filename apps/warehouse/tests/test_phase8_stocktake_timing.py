"""Phase 8 timing boundary: stale save, preserve expected, deliberate recount."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.rbac.services import seed_rbac_catalog
from apps.warehouse.models import SKU, Stock, Warehouse
from apps.warehouse.services import confirm_issue, request_issue_line
from apps.warehouse.stocktake import (
    mark_line_recount,
    save_line_count,
    start_stocktake,
)

User = get_user_model()


class Phase8StocktakeTimingBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.fm = User.objects.create_user(
            username="st8-t-fm",
            email="st8-t-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.wh = Warehouse.objects.create(code="ST8T", name="Timing WH")
        self.filter = SKU.objects.create(code="ST8T-F", name="Filter", unit="pcs")
        Stock.objects.create(sku=self.filter, warehouse=self.wh, quantity=Decimal("10"))

    def test_a_stale_count_before_save_rejected(self):
        st = start_stocktake(warehouse=self.wh, actor=self.fm)
        line = st.lines.get(sku=self.filter)
        # Form rendered while on-hand was 10
        displayed = "10"
        wo = WorkOrder.objects.create(
            code="WO-ST8T-A",
            title="Issue before save",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        issue = request_issue_line(
            work_order=wo,
            warehouse=self.wh,
            sku=self.filter,
            quantity=Decimal("2"),
            actor=self.fm,
        )
        confirm_issue(
            issue,
            actor=self.fm,
            lines=[{"id": issue.lines.get().pk, "issued_qty": "2", "unit_cost": "1"}],
        )
        self.assertEqual(Stock.objects.get(sku=self.filter, warehouse=self.wh).quantity, Decimal("8"))
        with self.assertRaises(DomainError) as ctx:
            save_line_count(
                line=line,
                counted_raw="10",
                actor=self.fm,
                displayed_on_hand=displayed,
            )
        self.assertIn("dəyişib", str(ctx.exception))
        line.refresh_from_db()
        self.assertIsNone(line.counted_qty)
        self.assertTrue(line.recount_required)
        # No postable surplus of +2
        self.assertIsNone(line.variance_qty)

    def test_b_resubmit_preserves_original_expected(self):
        st = start_stocktake(warehouse=self.wh, actor=self.fm)
        line = st.lines.get(sku=self.filter)
        save_line_count(line=line, counted_raw="10", actor=self.fm, displayed_on_hand="10")
        line.refresh_from_db()
        self.assertEqual(line.expected_qty, Decimal("10"))
        from apps.warehouse.services import apply_movement
        from apps.warehouse.models import StockMovementType

        apply_movement(
            sku=self.filter,
            warehouse=self.wh,
            movement_type=StockMovementType.RECEIPT,
            quantity=Decimal("3"),
            reference="AFTER",
        )
        # Resubmit same count (other lines / form reopen) must not refresh expected
        again = save_line_count(
            line=line, counted_raw="10", actor=self.fm, displayed_on_hand="13"
        )
        self.assertEqual(again.expected_qty, Decimal("10"))
        self.assertEqual(again.variance_qty, Decimal("0"))
        # Changing without recount is rejected
        with self.assertRaises(DomainError):
            save_line_count(line=line, counted_raw="9", actor=self.fm)

    def test_c_deliberate_recount_new_comparison(self):
        st = start_stocktake(warehouse=self.wh, actor=self.fm)
        line = st.lines.get(sku=self.filter)
        save_line_count(line=line, counted_raw="10", actor=self.fm, displayed_on_hand="10")
        from apps.warehouse.services import apply_movement
        from apps.warehouse.models import StockMovementType

        apply_movement(
            sku=self.filter,
            warehouse=self.wh,
            movement_type=StockMovementType.ISSUE,
            quantity=Decimal("1"),
            reference="ISS",
        )
        mark_line_recount(line=line, actor=self.fm, required=True)
        line.refresh_from_db()
        self.assertIsNone(line.counted_qty)
        self.assertTrue(line.recount_required)
        save_line_count(
            line=line, counted_raw="9", actor=self.fm, displayed_on_hand="9"
        )
        line.refresh_from_db()
        self.assertEqual(line.expected_qty, Decimal("9"))
        self.assertEqual(line.counted_qty, Decimal("9"))
        self.assertEqual(line.variance_qty, Decimal("0"))
        self.assertFalse(line.recount_required)
