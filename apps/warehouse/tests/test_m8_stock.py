from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.procurement.models import POStatus, PRStatus
from apps.procurement.services import ProcurementService
from apps.parties.models import Party
from apps.warehouse.models import SKU, Stock, StockMovementType, Warehouse
from apps.warehouse.services import apply_movement, confirm_issue, request_issue_line

User = get_user_model()


class M8StockProcurementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="wh-admin", email="wh-admin@test.az", password="x", role=Role.ADMIN
        )
        self.sku = SKU.objects.create(code="FILT", name="Filter", unit="ədəd", reorder_level=10)
        self.wh = Warehouse.objects.create(code="MAIN", name="Əsas")
        self.stock = Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("5"))
        self.wo = WorkOrder.objects.create(
            code="WO-M8-1",
            title="PM filter",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )

    def test_available_and_reservation(self):
        apply_movement(
            sku=self.sku,
            warehouse=self.wh,
            movement_type=StockMovementType.RESERVATION,
            quantity=Decimal("2"),
        )
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("5"))
        self.assertEqual(self.stock.reserved_quantity, Decimal("2"))
        self.assertEqual(self.stock.available_quantity, Decimal("3"))

    def test_wo_request_reserves_then_confirm_issues(self):
        issue = request_issue_line(
            work_order=self.wo,
            warehouse=self.wh,
            sku=self.sku,
            quantity=Decimal("2"),
            actor=self.admin,
        )
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, Decimal("2"))
        confirm_issue(
            issue,
            actor=self.admin,
            lines=[{"id": issue.lines.get().pk, "issued_qty": "2", "unit_cost": "1"}],
        )
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("3"))
        self.assertEqual(self.stock.reserved_quantity, Decimal("0"))

    def test_low_stock_pr_not_duplicated(self):
        self.stock.quantity = Decimal("1")
        self.stock.save(update_fields=["quantity"])
        pr1 = ProcurementService.create_pr_from_low_stock(stock=self.stock, requested_by=self.admin)
        pr2 = ProcurementService.create_pr_from_low_stock(stock=self.stock, requested_by=self.admin)
        self.assertEqual(pr1.pk, pr2.pk)
        self.assertEqual(pr1.status, PRStatus.SUBMITTED)

    def test_partial_po_receive(self):
        pr = ProcurementService.create_pr_from_low_stock(stock=self.stock, requested_by=self.admin)
        ProcurementService.approve_pr(pr, actor=self.admin)
        from apps.parties.models import PartyRole, PartyRoleCode

        supplier = Party.objects.create(legal_name="Supplier MMC")
        PartyRole.objects.get_or_create(party=supplier, role=PartyRoleCode.SUPPLIER)
        po = ProcurementService.create_po_from_pr(pr, supplier_party=supplier)
        line = po.lines.get()
        half = (line.qty or Decimal("1")) / 2
        if half <= 0:
            half = Decimal("1")
        ProcurementService.receive_po(
            po, warehouse=self.wh, actor=self.admin, line_qtys={line.pk: half}
        )
        po.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(po.status, POStatus.PARTIAL)
        self.assertEqual(line.received_qty, half)
