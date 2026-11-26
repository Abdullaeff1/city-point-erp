"""Phase 4.4.2.3 — goods receipt integrity (locking + durable idempotency)."""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.parties.models import Party, PartyRole, PartyRoleCode
from apps.procurement.models import GoodsReceiptOperation, POLine, PurchaseOrder
from apps.procurement.services import ProcurementService
from apps.procurement.tests.support import approve_pr_via_management, issue_priced_po
from apps.warehouse.models import SKU, Stock, StockMovement, StockMovementType, Warehouse

User = get_user_model()


def _stock_qty(sku, warehouse) -> Decimal:
    row = Stock.objects.filter(sku=sku, warehouse=warehouse).first()
    return row.quantity if row else Decimal("0")


def _receipt_movements(po_code: str, sku=None):
    qs = StockMovement.objects.filter(
        reference=po_code, movement_type=StockMovementType.RECEIPT
    )
    if sku is not None:
        qs = qs.filter(sku=sku)
    return qs


class _ReceiptFixtureMixin:
    def _seed_common(self, suffix: str):
        self.admin = User.objects.create_user(
            username=f"gr-{suffix}-adm",
            email=f"gr-{suffix}-adm@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.viewer = User.objects.create_user(
            username=f"gr-{suffix}-view",
            email=f"gr-{suffix}-view@test.az",
            password="x",
            role=Role.RECEPTION,
            is_staff=True,
        )
        self.sku = SKU.objects.create(code=f"GR-{suffix}-A", name="Item A", unit="pcs", reorder_level=0)
        self.sku_b = SKU.objects.create(code=f"GR-{suffix}-B", name="Item B", unit="pcs", reorder_level=0)
        self.wh = Warehouse.objects.create(code=f"GR{suffix}W1", name="WH1")
        self.wh2 = Warehouse.objects.create(code=f"GR{suffix}W2", name="WH2")
        Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("0"))
        Stock.objects.create(sku=self.sku_b, warehouse=self.wh, quantity=Decimal("0"))
        Stock.objects.create(sku=self.sku, warehouse=self.wh2, quantity=Decimal("5"))
        self.supplier = Party.objects.create(legal_name=f"GR Supplier {suffix}")
        PartyRole.objects.get_or_create(party=self.supplier, role=PartyRoleCode.SUPPLIER)

    def _make_po(self, *, qty=Decimal("10"), sku=None, extra_lines=None) -> PurchaseOrder:
        sku = sku or self.sku
        pr = ProcurementService.create_manual_pr(
            actor=self.admin,
            title=f"GR PR {uuid.uuid4().hex[:8]}",
            lines=[{"description": "Line A", "qty": str(qty), "sku_id": sku.pk}],
        )
        # Mandatory Management policy: PR + priced commitment approved before issue.
        approve_pr_via_management(pr, actor=self.admin)
        po = issue_priced_po(pr, supplier=self.supplier, unit_price="10", actor=self.admin)
        if extra_lines:
            for spec in extra_lines:
                POLine.objects.create(
                    po=po,
                    description=spec.get("description", "Extra"),
                    sku=spec["sku"],
                    qty=Decimal(str(spec["qty"])),
                )
        return po


class GoodsReceiptIntegrityTests(_ReceiptFixtureMixin, TestCase):
    def setUp(self):
        self._seed_common("tc")

    def test_B_partial_replay_same_key(self):
        po = self._make_po(qty=Decimal("10"))
        line = po.lines.get()
        key = uuid.uuid4().hex
        before = _stock_qty(self.sku, self.wh)
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4"},
            operation_key=key,
            receive_mode="partial",
        )
        result = ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4.00"},
            operation_key=key,
            receive_mode="partial",
        )
        self.assertTrue(getattr(result, "receipt_replayed", False))
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("4.000"))
        self.assertEqual((line.qty - line.received_qty), Decimal("6.000"))
        self.assertEqual(po.status, "partial")
        self.assertEqual(_stock_qty(self.sku, self.wh), before + Decimal("4"))
        self.assertEqual(_receipt_movements(po.code, self.sku).count(), 1)
        self.assertEqual(GoodsReceiptOperation.objects.filter(operation_key=key).count(), 1)

    def test_D_partial_then_remainder_new_key(self):
        po = self._make_po(qty=Decimal("10"))
        line = po.lines.get()
        before = _stock_qty(self.sku, self.wh)
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4"},
            operation_key=uuid.uuid4().hex,
            receive_mode="partial",
        )
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "6"},
            operation_key=uuid.uuid4().hex,
            receive_mode="partial",
        )
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("10.000"))
        self.assertEqual(po.status, "received")
        self.assertEqual(_stock_qty(self.sku, self.wh), before + Decimal("10"))
        self.assertEqual(_receipt_movements(po.code, self.sku).count(), 2)

    def test_E_two_genuine_partials(self):
        po = self._make_po(qty=Decimal("10"))
        line = po.lines.get()
        before = _stock_qty(self.sku, self.wh)
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4"},
            operation_key=uuid.uuid4().hex,
            receive_mode="partial",
        )
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4"},
            operation_key=uuid.uuid4().hex,
            receive_mode="partial",
        )
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("8.000"))
        self.assertEqual(line.qty - line.received_qty, Decimal("2.000"))
        self.assertEqual(po.status, "partial")
        self.assertEqual(_stock_qty(self.sku, self.wh), before + Decimal("8"))
        self.assertEqual(_receipt_movements(po.code, self.sku).count(), 2)
        self.assertEqual(GoodsReceiptOperation.objects.filter(po=po).count(), 2)

    def test_F_same_key_payload_conflict(self):
        po = self._make_po(qty=Decimal("10"))
        line = po.lines.get()
        key = uuid.uuid4().hex
        before = _stock_qty(self.sku, self.wh)
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4"},
            operation_key=key,
            receive_mode="partial",
        )
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(
                po,
                warehouse=self.wh,
                actor=self.admin,
                line_qtys={line.pk: "5"},
                operation_key=key,
                receive_mode="partial",
            )
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(
                po,
                warehouse=self.wh2,
                actor=self.admin,
                line_qtys={line.pk: "4"},
                operation_key=key,
                receive_mode="partial",
            )
        line.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("4.000"))
        self.assertEqual(_stock_qty(self.sku, self.wh), before + Decimal("4"))
        self.assertEqual(_receipt_movements(po.code, self.sku).count(), 1)

    def test_G_multiline_rollback_on_later_line(self):
        po = self._make_po(
            qty=Decimal("5"),
            extra_lines=[{"sku": self.sku_b, "qty": "3", "description": "B"}],
        )
        lines = list(po.lines.order_by("pk"))
        before_a = _stock_qty(self.sku, self.wh)
        before_b = _stock_qty(self.sku_b, self.wh)
        ops_before = GoodsReceiptOperation.objects.count()
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(
                po,
                warehouse=self.wh,
                actor=self.admin,
                line_qtys={lines[0].pk: "2", lines[1].pk: "99"},
                operation_key=uuid.uuid4().hex,
                receive_mode="partial",
            )
        for ln in lines:
            ln.refresh_from_db()
            self.assertEqual(ln.received_qty, Decimal("0"))
        po.refresh_from_db()
        self.assertEqual(po.status, "sent")
        self.assertEqual(_stock_qty(self.sku, self.wh), before_a)
        self.assertEqual(_stock_qty(self.sku_b, self.wh), before_b)
        self.assertEqual(_receipt_movements(po.code).count(), 0)
        self.assertEqual(GoodsReceiptOperation.objects.count(), ops_before)

    def test_H_full_replay_then_new_key_rejected(self):
        po = self._make_po(qty=Decimal("10"))
        key = uuid.uuid4().hex
        before = _stock_qty(self.sku, self.wh)
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            operation_key=key,
            receive_mode="full",
        )
        po.refresh_from_db()
        self.assertEqual(po.status, "received")
        replay = ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            operation_key=key,
            receive_mode="full",
        )
        self.assertTrue(getattr(replay, "receipt_replayed", False))
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(
                po,
                warehouse=self.wh,
                actor=self.admin,
                operation_key=uuid.uuid4().hex,
                receive_mode="full",
            )
        line = po.lines.get()
        line.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("10.000"))
        self.assertEqual(_stock_qty(self.sku, self.wh), before + Decimal("10"))
        self.assertEqual(_receipt_movements(po.code, self.sku).count(), 1)

    def test_I_ui_auth_and_validation(self):
        po = self._make_po(qty=Decimal("10"))
        line = po.lines.get()
        other_po = self._make_po(qty=Decimal("2"))
        foreign_line = other_po.lines.get()
        before = _stock_qty(self.sku, self.wh)

        client = Client()
        # Unauthorized
        client.force_login(self.viewer)
        resp = client.post(
            reverse("erp:procurement"),
            {
                "action": "receive_po",
                "po_id": str(po.pk),
                "warehouse_id": str(self.wh.pk),
                "receive_mode": "full",
                "operation_key": uuid.uuid4().hex,
            },
        )
        self.assertIn(resp.status_code, (302, 403))
        po.refresh_from_db()
        self.assertEqual(po.status, "sent")

        client.force_login(self.admin)
        # Missing warehouse on detail
        resp = client.post(
            reverse("erp:procurement_po_detail", kwargs={"code": po.code}),
            {
                "action": "receive_po",
                "receive_mode": "partial",
                "operation_key": uuid.uuid4().hex,
                f"recv_qty_{line.pk}": "1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        po.refresh_from_db()
        self.assertEqual(po.status, "sent")

        # Foreign line
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(
                po,
                warehouse=self.wh,
                actor=self.admin,
                line_qtys={foreign_line.pk: "1"},
                operation_key=uuid.uuid4().hex,
                receive_mode="partial",
            )

        # Negative
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(
                po,
                warehouse=self.wh,
                actor=self.admin,
                line_qtys={line.pk: "-1"},
                operation_key=uuid.uuid4().hex,
                receive_mode="partial",
            )

        # Empty partial
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(
                po,
                warehouse=self.wh,
                actor=self.admin,
                line_qtys={},
                operation_key=uuid.uuid4().hex,
                receive_mode="partial",
            )
        resp = client.post(
            reverse("erp:procurement_po_detail", kwargs={"code": po.code}),
            {
                "action": "receive_po",
                "warehouse_id": str(self.wh.pk),
                "receive_mode": "partial",
                "operation_key": uuid.uuid4().hex,
            },
        )
        self.assertEqual(resp.status_code, 302)
        po.refresh_from_db()
        self.assertEqual(po.status, "sent")
        self.assertEqual(_stock_qty(self.sku, self.wh), before)
        self.assertEqual(_receipt_movements(po.code).count(), 0)

    def test_J_selected_warehouse_and_sku_only(self):
        po = self._make_po(
            qty=Decimal("4"),
            extra_lines=[{"sku": self.sku_b, "qty": "2", "description": "B"}],
        )
        lines = list(po.lines.order_by("pk"))
        before_wh = _stock_qty(self.sku, self.wh)
        before_wh2 = _stock_qty(self.sku, self.wh2)
        before_b = _stock_qty(self.sku_b, self.wh)
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={lines[0].pk: "4", lines[1].pk: "2"},
            operation_key=uuid.uuid4().hex,
            receive_mode="partial",
        )
        self.assertEqual(_stock_qty(self.sku, self.wh), before_wh + Decimal("4"))
        self.assertEqual(_stock_qty(self.sku_b, self.wh), before_b + Decimal("2"))
        self.assertEqual(_stock_qty(self.sku, self.wh2), before_wh2)
        self.assertEqual(_receipt_movements(po.code, self.sku).filter(warehouse=self.wh).count(), 1)
        self.assertEqual(_receipt_movements(po.code, self.sku_b).filter(warehouse=self.wh).count(), 1)
        self.assertEqual(_receipt_movements(po.code).filter(warehouse=self.wh2).count(), 0)

    def test_failed_attempt_then_valid_retry_same_key(self):
        po = self._make_po(qty=Decimal("10"))
        line = po.lines.get()
        key = uuid.uuid4().hex
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(
                po,
                warehouse=self.wh,
                actor=self.admin,
                line_qtys={line.pk: "99"},
                operation_key=key,
                receive_mode="partial",
            )
        self.assertFalse(GoodsReceiptOperation.objects.filter(operation_key=key).exists())
        before = _stock_qty(self.sku, self.wh)
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4"},
            operation_key=key,
            receive_mode="partial",
        )
        line.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("4.000"))
        self.assertEqual(_stock_qty(self.sku, self.wh), before + Decimal("4"))

    def test_both_ui_entry_points_receive(self):
        po_list = self._make_po(qty=Decimal("3"))
        po_detail = self._make_po(qty=Decimal("5"))
        line = po_detail.lines.get()
        client = Client()
        client.force_login(self.admin)
        key1 = uuid.uuid4().hex
        resp = client.post(
            reverse("erp:procurement"),
            {
                "action": "receive_po",
                "po_id": str(po_list.pk),
                "warehouse_id": str(self.wh.pk),
                "receive_mode": "full",
                "operation_key": key1,
            },
        )
        self.assertEqual(resp.status_code, 302)
        po_list.refresh_from_db()
        self.assertEqual(po_list.status, "received")
        # Replay via list URL
        resp = client.post(
            reverse("erp:procurement"),
            {
                "action": "receive_po",
                "po_id": str(po_list.pk),
                "warehouse_id": str(self.wh.pk),
                "receive_mode": "full",
                "operation_key": key1,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(_receipt_movements(po_list.code).count(), 1)

        key2 = uuid.uuid4().hex
        resp = client.post(
            reverse("erp:procurement_po_detail", kwargs={"code": po_detail.code}),
            {
                "action": "receive_po",
                "warehouse_id": str(self.wh.pk),
                "receive_mode": "partial",
                "operation_key": key2,
                f"recv_qty_{line.pk}": "2",
            },
        )
        self.assertEqual(resp.status_code, 302)
        line.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("2.000"))
        resp = client.post(
            reverse("erp:procurement_po_detail", kwargs={"code": po_detail.code}),
            {
                "action": "receive_po",
                "warehouse_id": str(self.wh.pk),
                "receive_mode": "partial",
                "operation_key": key2,
                f"recv_qty_{line.pk}": "2",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(_receipt_movements(po_detail.code).count(), 1)


class GoodsReceiptConcurrencyTests(_ReceiptFixtureMixin, TransactionTestCase):
    def setUp(self):
        self._seed_common("pg")

    def test_A_two_operators_last_ten_units(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-level locks")

        po = self._make_po(qty=Decimal("10"))
        line = po.lines.get()
        before = _stock_qty(self.sku, self.wh)
        po_id = po.pk
        line_id = line.pk
        wh_id = self.wh.pk
        admin_id = self.admin.pk
        barrier = threading.Barrier(2, timeout=20)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker(op_key: str):
            connections.close_all()
            try:
                barrier.wait()
                actor = User.objects.get(pk=admin_id)
                locked_po = PurchaseOrder.objects.get(pk=po_id)
                wh = Warehouse.objects.get(pk=wh_id)
                ProcurementService.receive_po(
                    locked_po,
                    warehouse=wh,
                    actor=actor,
                    line_qtys={line_id: "10"},
                    operation_key=op_key,
                    receive_mode="partial",
                )
                with lock:
                    outcomes.append("ok")
            except DomainError as exc:
                with lock:
                    outcomes.append(f"domain:{exc}")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    outcomes.append(f"{type(exc).__name__}:{exc}")
            finally:
                connections.close_all()

        keys = [uuid.uuid4().hex, uuid.uuid4().hex]
        threads = [threading.Thread(target=worker, args=(k,)) for k in keys]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
            self.assertFalse(t.is_alive(), "worker hung")

        self.assertEqual(outcomes.count("ok"), 1, outcomes)
        self.assertEqual(len(outcomes), 2, outcomes)
        line = POLine.objects.get(pk=line_id)
        po = PurchaseOrder.objects.get(pk=po_id)
        self.assertEqual(line.received_qty, Decimal("10.000"))
        self.assertEqual(po.status, "received")
        self.assertEqual(_stock_qty(self.sku, self.wh), before + Decimal("10"))
        self.assertEqual(_receipt_movements(po.code, self.sku).count(), 1)

    def test_C_same_key_concurrent_partial(self):
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL row-level locks")

        po = self._make_po(qty=Decimal("10"))
        line = po.lines.get()
        before = _stock_qty(self.sku, self.wh)
        po_id = po.pk
        line_id = line.pk
        wh_id = self.wh.pk
        admin_id = self.admin.pk
        key = uuid.uuid4().hex
        barrier = threading.Barrier(2, timeout=20)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker():
            connections.close_all()
            try:
                barrier.wait()
                actor = User.objects.get(pk=admin_id)
                locked_po = PurchaseOrder.objects.get(pk=po_id)
                wh = Warehouse.objects.get(pk=wh_id)
                result = ProcurementService.receive_po(
                    locked_po,
                    warehouse=wh,
                    actor=actor,
                    line_qtys={line_id: "4"},
                    operation_key=key,
                    receive_mode="partial",
                )
                tag = "replay" if getattr(result, "receipt_replayed", False) else "ok"
                with lock:
                    outcomes.append(tag)
            except DomainError as exc:
                with lock:
                    outcomes.append(f"domain:{exc}")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    outcomes.append(f"{type(exc).__name__}:{exc}")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)
            self.assertFalse(t.is_alive(), "worker hung")

        self.assertEqual(sorted(outcomes), ["ok", "replay"], outcomes)
        line = POLine.objects.get(pk=line_id)
        po = PurchaseOrder.objects.get(pk=po_id)
        self.assertEqual(line.received_qty, Decimal("4.000"))
        self.assertEqual(line.qty - line.received_qty, Decimal("6.000"))
        self.assertEqual(po.status, "partial")
        self.assertEqual(_stock_qty(self.sku, self.wh), before + Decimal("4"))
        self.assertEqual(_receipt_movements(po.code, self.sku).count(), 1)
        self.assertEqual(GoodsReceiptOperation.objects.filter(operation_key=key).count(), 1)
