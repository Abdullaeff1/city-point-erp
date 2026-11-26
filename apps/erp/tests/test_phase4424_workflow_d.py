"""Cross-module acceptance: Facility → Procurement → Warehouse → WO cost (Workflow D)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.maintenance.costs import sync_procurement_cost
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.maintenance.services import next_wo_code
from apps.parties.models import Party, PartyRole, PartyRoleCode
from apps.procurement.models import GoodsReceiptOperation, POLine
from apps.procurement.services import ProcurementService
from apps.procurement.tests.support import approve_pr_via_management, issue_priced_po
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.warehouse.models import SKU, Stock, StockMovement, StockMovementType, Warehouse
from apps.warehouse.services import confirm_issue, request_issue_line

User = get_user_model()


class WorkflowDProcurementChainTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.admin = User.objects.create_user(
            username="wfd-adm",
            email="wfd-adm@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.fm = User.objects.create_user(
            username="wfd-fm",
            email="wfd-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(self.fm, "supply.head")
        self.wh = Warehouse.objects.create(code="WFD-WH", name="WFD WH")
        self.sku = SKU.objects.create(code="WFD-SKU", name="Cable", unit="m", reorder_level=0)
        Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("0"))
        self.wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="WFD cable job",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        self.supplier = Party.objects.create(legal_name="WFD Supplier")
        PartyRole.objects.get_or_create(party=self.supplier, role=PartyRoleCode.SUPPLIER)

    def test_wo_pr_po_two_receipts_replay_then_issue(self):
        # 1) WO-linked PR
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="Cable", qty="10", sku=self.sku
        )
        self.assertEqual(pr.work_order_id, self.wo.pk)

        # 2) Mandatory Management approval of the PR (no Admin bypass)
        approve_pr_via_management(pr, actor=self.admin)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "approved")

        # 3) Priced PO with supplier — Management commitment approved before issue
        po = issue_priced_po(
            pr, supplier=self.supplier, unit_price="2.50", actor=self.admin
        )
        line = po.lines.get()
        self.assertEqual(line.unit_price, Decimal("2.50"))
        self.assertEqual(line.qty, Decimal("10"))

        before = Stock.objects.get(sku=self.sku, warehouse=self.wh).quantity
        key1 = uuid.uuid4().hex
        key2 = uuid.uuid4().hex

        # 4) Two genuine partial deliveries
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4"},
            operation_key=key1,
            receive_mode="partial",
        )
        line.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("4.000"))
        self.assertEqual(
            Stock.objects.get(sku=self.sku, warehouse=self.wh).quantity,
            before + Decimal("4"),
        )

        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "6"},
            operation_key=key2,
            receive_mode="partial",
        )
        line.refresh_from_db()
        po.refresh_from_db()
        self.assertEqual(line.received_qty, Decimal("10.000"))
        self.assertEqual(po.status, "received")
        self.assertEqual(
            Stock.objects.get(sku=self.sku, warehouse=self.wh).quantity,
            before + Decimal("10"),
        )
        self.assertEqual(
            StockMovement.objects.filter(
                reference=po.code, movement_type=StockMovementType.RECEIPT
            ).count(),
            2,
        )

        # 5) Replay committed receipt — no second movement
        replay = ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=self.admin,
            line_qtys={line.pk: "4"},
            operation_key=key1,
            receive_mode="partial",
        )
        self.assertTrue(getattr(replay, "receipt_replayed", False))
        self.assertEqual(GoodsReceiptOperation.objects.filter(operation_key=key1).count(), 1)
        self.assertEqual(
            StockMovement.objects.filter(
                reference=po.code, movement_type=StockMovementType.RECEIPT
            ).count(),
            2,
        )

        # 6) Outstanding / stock after chain
        outstanding = (line.qty or Decimal("0")) - (line.received_qty or Decimal("0"))
        self.assertEqual(outstanding, Decimal("0"))

        # 7) Issue material back to WO + confirm
        issue = request_issue_line(
            work_order=self.wo,
            warehouse=self.wh,
            sku=self.sku,
            quantity=Decimal("3"),
            actor=self.fm,
        )
        issue_line = issue.lines.get()
        confirm_issue(
            issue,
            actor=self.fm,
            lines=[{"id": issue_line.pk, "issued_qty": "3", "unit_cost": "2.50"}],
        )
        stock = Stock.objects.get(sku=self.sku, warehouse=self.wh)
        self.assertEqual(stock.quantity, before + Decimal("7"))
        self.assertTrue(
            StockMovement.objects.filter(
                work_order=self.wo, movement_type=StockMovementType.ISSUE
            ).exists()
        )

        # 8) WO procurement cost sync
        sync_procurement_cost(self.wo)
        self.wo.refresh_from_db()
        self.assertEqual(POLine.objects.filter(po=po).count(), 1)
