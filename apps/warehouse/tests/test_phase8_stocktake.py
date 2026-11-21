"""Product Delivery Phase 8 — warehouse stocktake / variance / controlled post."""

from __future__ import annotations

from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.core.services import DomainError
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.rbac.services import seed_rbac_catalog
from apps.warehouse.models import (
    SKU,
    Stock,
    StockMovement,
    StockMovementType,
    Stocktake,
    StocktakeLine,
    StocktakeStatus,
    Warehouse,
)
from apps.warehouse.services import apply_movement, confirm_issue, request_issue_line
from apps.warehouse.stocktake import (
    add_found_sku,
    complete_stocktake,
    post_stocktake_variances,
    save_line_count,
    start_stocktake,
    stocktake_progress,
)

User = get_user_model()


class Phase8StocktakeBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.client = Client()
        self.fm = User.objects.create_user(
            username="st8-fm",
            email="st8-fm@test.az",
            password="x",
            role=Role.PROPERTY_FM,
            is_staff=True,
        )
        self.mgmt = User.objects.create_user(
            username="st8-mgmt",
            email="st8-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.wh_a = Warehouse.objects.create(code="ST8A", name="Stocktake A")
        self.wh_b = Warehouse.objects.create(code="ST8B", name="Stocktake B")
        self.filter = SKU.objects.create(code="ST8-FILTER", name="HVAC filter", unit="pcs", reorder_level=2)
        self.oil = SKU.objects.create(code="ST8-OIL", name="Gear oil", unit="L", reorder_level=5)
        self.cable = SKU.objects.create(code="ST8-CABLE", name="Control cable", unit="m", reorder_level=10)
        self.orphan = SKU.objects.create(code="ST8-ORPHAN", name="Found gasket", unit="pcs", reorder_level=0)
        Stock.objects.create(sku=self.filter, warehouse=self.wh_a, quantity=Decimal("10"), reserved_quantity=Decimal("3"))
        Stock.objects.create(sku=self.oil, warehouse=self.wh_a, quantity=Decimal("20.500"))
        Stock.objects.create(sku=self.cable, warehouse=self.wh_a, quantity=Decimal("100"))
        Stock.objects.create(sku=self.filter, warehouse=self.wh_b, quantity=Decimal("50"))


class Phase8StocktakeServiceTests(Phase8StocktakeBase):
    def test_a_start_partial_save_resume(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        self.assertEqual(st.status, StocktakeStatus.OPEN)
        self.assertEqual(st.lines.count(), 3)
        line = st.lines.get(sku=self.filter)
        save_line_count(line=line, counted_raw="10", actor=self.fm)
        progress = stocktake_progress(st)
        self.assertEqual(progress["counted_lines"], 1)
        self.assertEqual(progress["outstanding_lines"], 2)
        st2 = Stocktake.objects.get(pk=st.pk)
        self.assertEqual(st2.lines.get(sku=self.filter).counted_qty, Decimal("10"))
        self.assertIsNone(st2.lines.get(sku=self.oil).counted_qty)

    def test_b_uncounted_vs_explicit_zero_shortage(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        oil = st.lines.get(sku=self.oil)
        filt = st.lines.get(sku=self.filter)
        with self.assertRaises(DomainError):
            save_line_count(line=oil, counted_raw="  ", actor=self.fm)
        oil.refresh_from_db()
        self.assertIsNone(oil.counted_qty)
        save_line_count(line=filt, counted_raw="0", actor=self.fm)
        filt.refresh_from_db()
        self.assertEqual(filt.counted_qty, Decimal("0"))
        self.assertEqual(filt.expected_qty, Decimal("10"))
        self.assertEqual(filt.variance_qty, Decimal("-10"))
        self.assertEqual(filt.variance_kind, "shortage")

    def test_c_match_surplus_shortage_warehouse_scoped(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        save_line_count(line=st.lines.get(sku=self.filter), counted_raw="10", actor=self.fm)
        save_line_count(line=st.lines.get(sku=self.oil), counted_raw="22.500", actor=self.fm)
        save_line_count(line=st.lines.get(sku=self.cable), counted_raw="90", actor=self.fm)
        complete_stocktake(stocktake=st, actor=self.fm)
        post_stocktake_variances(stocktake=st, actor=self.fm, reason="Phase8 C")
        st.refresh_from_db()
        self.assertEqual(st.status, StocktakeStatus.POSTED)
        # Match → no adjustment for filter
        self.assertIsNone(st.lines.get(sku=self.filter).adjustment_movement_id)
        oil_line = st.lines.get(sku=self.oil)
        cable_line = st.lines.get(sku=self.cable)
        self.assertIsNotNone(oil_line.adjustment_movement_id)
        self.assertIsNotNone(cable_line.adjustment_movement_id)
        self.assertEqual(oil_line.variance_qty, Decimal("2.000"))
        self.assertEqual(cable_line.variance_qty, Decimal("-10"))
        self.assertEqual(Stock.objects.get(sku=self.oil, warehouse=self.wh_a).quantity, Decimal("22.500"))
        self.assertEqual(Stock.objects.get(sku=self.cable, warehouse=self.wh_a).quantity, Decimal("90"))
        # Other warehouse untouched
        self.assertEqual(Stock.objects.get(sku=self.filter, warehouse=self.wh_b).quantity, Decimal("50"))
        adj = StockMovement.objects.filter(
            warehouse=self.wh_a, movement_type=StockMovementType.ADJUSTMENT, reference__startswith="ST:"
        )
        self.assertEqual(adj.count(), 2)

    def test_d_found_sku_without_balance(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        line = add_found_sku(stocktake=st, sku=self.orphan, actor=self.fm)
        self.assertEqual(line.baseline_qty, Decimal("0"))
        self.assertEqual(line.unit, "pcs")
        save_line_count(line=line, counted_raw="4", actor=self.fm)
        line.refresh_from_db()
        self.assertEqual(line.expected_qty, Decimal("0"))
        self.assertEqual(line.variance_qty, Decimal("4"))
        complete_stocktake(stocktake=st, actor=self.fm)
        post_stocktake_variances(stocktake=st, actor=self.fm, reason="found")
        stock = Stock.objects.get(sku=self.orphan, warehouse=self.wh_a)
        self.assertEqual(stock.quantity, Decimal("4"))

    def test_e_reserved_is_physical_on_hand(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        line = st.lines.get(sku=self.filter)
        self.assertEqual(line.baseline_qty, Decimal("10"))  # not available 7
        save_line_count(line=line, counted_raw="10", actor=self.fm)
        line.refresh_from_db()
        self.assertEqual(line.expected_qty, Decimal("10"))
        self.assertEqual(line.variance_qty, Decimal("0"))

    def test_f_issue_during_count_zero_variance(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        line = st.lines.get(sku=self.filter)
        self.assertEqual(line.baseline_qty, Decimal("10"))
        wo = WorkOrder.objects.create(
            code="WO-ST8-F",
            title="Issue during count",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        issue = request_issue_line(
            work_order=wo,
            warehouse=self.wh_a,
            sku=self.filter,
            quantity=Decimal("2"),
            actor=self.fm,
        )
        confirm_issue(
            issue,
            actor=self.fm,
            lines=[{"id": issue.lines.get().pk, "issued_qty": "2", "unit_cost": "1"}],
        )
        self.assertEqual(Stock.objects.get(sku=self.filter, warehouse=self.wh_a).quantity, Decimal("8"))
        save_line_count(line=line, counted_raw="8", actor=self.fm)
        line.refresh_from_db()
        self.assertEqual(line.expected_qty, Decimal("8"))
        self.assertEqual(line.variance_qty, Decimal("0"))
        complete_stocktake(stocktake=st, actor=self.fm)
        post_stocktake_variances(stocktake=st, actor=self.fm, reason="timing A")
        self.assertIsNone(st.lines.get(sku=self.filter).adjustment_movement_id)
        self.assertEqual(Stock.objects.get(sku=self.filter, warehouse=self.wh_a).quantity, Decimal("8"))

    def test_g_receipt_after_count_preserved_on_post(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        line = st.lines.get(sku=self.filter)
        save_line_count(line=line, counted_raw="8", actor=self.fm)
        line.refresh_from_db()
        self.assertEqual(line.expected_qty, Decimal("10"))
        self.assertEqual(line.variance_qty, Decimal("-2"))
        apply_movement(
            sku=self.filter,
            warehouse=self.wh_a,
            movement_type=StockMovementType.RECEIPT,
            quantity=Decimal("3"),
            reference="RCV-AFTER",
        )
        self.assertEqual(Stock.objects.get(sku=self.filter, warehouse=self.wh_a).quantity, Decimal("13"))
        complete_stocktake(stocktake=st, actor=self.fm)
        post_stocktake_variances(stocktake=st, actor=self.fm, reason="timing B")
        # current 13 + variance -2 = 11 (receipt kept)
        self.assertEqual(Stock.objects.get(sku=self.filter, warehouse=self.wh_a).quantity, Decimal("11"))
        line.refresh_from_db()
        self.assertEqual(line.expected_qty, Decimal("10"))
        self.assertEqual(line.counted_qty, Decimal("8"))
        self.assertEqual(line.variance_qty, Decimal("-2"))

    def test_h_idempotent_post(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        save_line_count(line=st.lines.get(sku=self.cable), counted_raw="95", actor=self.fm)
        complete_stocktake(stocktake=st, actor=self.fm)
        post_stocktake_variances(stocktake=st, actor=self.fm, reason="once")
        post_stocktake_variances(stocktake=st, actor=self.fm, reason="retry")
        adj = StockMovement.objects.filter(
            sku=self.cable, warehouse=self.wh_a, movement_type=StockMovementType.ADJUSTMENT
        )
        self.assertEqual(adj.count(), 1)
        self.assertEqual(Stock.objects.get(sku=self.cable, warehouse=self.wh_a).quantity, Decimal("95"))

    def test_i_management_cannot_post_direct(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        save_line_count(line=st.lines.get(sku=self.filter), counted_raw="9", actor=self.fm)
        complete_stocktake(stocktake=st, actor=self.fm)
        with self.assertRaises(DomainError):
            post_stocktake_variances(stocktake=st, actor=self.mgmt, reason="nope")
        self.client.force_login(self.mgmt)
        url = reverse("erp:stocktake_detail", kwargs={"code": st.code})
        r = self.client.post(
            url,
            {"action": "post_variances", "reason": "hack", "submit_token": "t1"},
        )
        self.assertIn(r.status_code, (302, 403))
        st.refresh_from_db()
        self.assertEqual(st.status, StocktakeStatus.COMPLETED)
        self.assertEqual(Stock.objects.get(sku=self.filter, warehouse=self.wh_a).quantity, Decimal("10"))

    def test_j_historical_report_frozen(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        line = st.lines.get(sku=self.filter)
        save_line_count(line=line, counted_raw="9", actor=self.fm)
        complete_stocktake(stocktake=st, actor=self.fm)
        post_stocktake_variances(stocktake=st, actor=self.fm, reason="freeze")
        line.refresh_from_db()
        snap_exp, snap_cnt, snap_var = line.expected_qty, line.counted_qty, line.variance_qty
        apply_movement(
            sku=self.filter,
            warehouse=self.wh_a,
            movement_type=StockMovementType.RECEIPT,
            quantity=Decimal("5"),
            reference="LATER",
        )
        line.refresh_from_db()
        self.assertEqual(line.expected_qty, snap_exp)
        self.assertEqual(line.counted_qty, snap_cnt)
        self.assertEqual(line.variance_qty, snap_var)
        self.client.force_login(self.fm)
        r = self.client.get(reverse("erp:stocktake_detail", kwargs={"code": st.code}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "9")
        self.assertContains(r, st.code)

    def test_partial_complete_does_not_shortage_uncounted(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        save_line_count(line=st.lines.get(sku=self.filter), counted_raw="10", actor=self.fm)
        complete_stocktake(stocktake=st, actor=self.fm)
        post_stocktake_variances(stocktake=st, actor=self.fm, reason="partial")
        self.assertEqual(Stock.objects.get(sku=self.oil, warehouse=self.wh_a).quantity, Decimal("20.500"))
        self.assertEqual(Stock.objects.get(sku=self.cable, warehouse=self.wh_a).quantity, Decimal("100"))
        oil = st.lines.get(sku=self.oil)
        self.assertIsNone(oil.counted_qty)
        self.assertIsNone(oil.adjustment_movement_id)

    def test_negative_count_rejected(self):
        st = start_stocktake(warehouse=self.wh_a, actor=self.fm)
        with self.assertRaises(DomainError):
            save_line_count(line=st.lines.get(sku=self.filter), counted_raw="-1", actor=self.fm)


class Phase8StocktakeHttpWalkthrough(Phase8StocktakeBase):
    def test_authenticated_http_walkthrough(self):
        self.client.force_login(self.fm)
        list_url = reverse("erp:stocktake_list")
        r = self.client.get(list_url)
        self.assertEqual(r.status_code, 200)
        r = self.client.post(
            list_url,
            {
                "action": "start",
                "warehouse_id": self.wh_a.pk,
                "notes": "UAT walk",
                "submit_token": "walk-start",
            },
        )
        self.assertEqual(r.status_code, 302)
        st = Stocktake.objects.get(warehouse=self.wh_a, status=StocktakeStatus.OPEN)
        detail = reverse("erp:stocktake_detail", kwargs={"code": st.code})
        self.assertIn(st.code, r["Location"])
        line_f = st.lines.get(sku=self.filter)
        line_o = st.lines.get(sku=self.oil)
        r = self.client.post(
            detail,
            {
                "action": "save_counts",
                f"count_{line_f.pk}": "10",
                "submit_token": "walk-save1",
            },
        )
        self.assertEqual(r.status_code, 302)
        # Resume: oil empty field omitted
        r = self.client.post(
            detail,
            {
                "action": "save_counts",
                f"count_{line_o.pk}": "20.500",
                f"count_{st.lines.get(sku=self.cable).pk}": "100",
                "submit_token": "walk-save2",
            },
        )
        self.assertEqual(r.status_code, 302)
        r = self.client.post(detail, {"action": "complete", "submit_token": "walk-done"})
        self.assertEqual(r.status_code, 302)
        st.refresh_from_db()
        self.assertEqual(st.status, StocktakeStatus.COMPLETED)
        r = self.client.get(detail)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Sayım hesabatı")
        self.assertTrue(AuditLog.objects.filter(action="warehouse.stocktake.complete").exists())


class Phase8StocktakeConcurrentPost(TransactionTestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.fm = User.objects.create_user(
            username="st8-conc-fm",
            email="st8-conc@test.az",
            password="x",
            role=Role.PROPERTY_FM,
            is_staff=True,
        )
        self.wh = Warehouse.objects.create(code="ST8C", name="Concurrent WH")
        self.sku = SKU.objects.create(code="ST8-CONC", name="Bolt", unit="pcs")
        Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("10"))
        self.st = start_stocktake(warehouse=self.wh, actor=self.fm)
        save_line_count(line=self.st.lines.get(), counted_raw="7", actor=self.fm)
        complete_stocktake(stocktake=self.st, actor=self.fm)

    def test_concurrent_post_one_adjustment(self):
        barrier = Barrier(2)
        results = []

        def worker():
            barrier.wait()
            try:
                post_stocktake_variances(stocktake=self.st, actor=self.fm, reason="race")
                results.append("ok")
            except DomainError as exc:
                results.append(str(exc))
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [pool.submit(worker), pool.submit(worker)]
            for f in futs:
                f.result()
        self.st.refresh_from_db()
        self.assertEqual(self.st.status, StocktakeStatus.POSTED)
        self.assertEqual(
            StockMovement.objects.filter(
                sku=self.sku, warehouse=self.wh, movement_type=StockMovementType.ADJUSTMENT
            ).count(),
            1,
        )
        self.assertEqual(Stock.objects.get(sku=self.sku, warehouse=self.wh).quantity, Decimal("7"))
