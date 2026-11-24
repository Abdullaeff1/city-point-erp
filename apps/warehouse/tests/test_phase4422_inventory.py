"""Phase 4.4.2.2 — Warehouse / inventory operator workflows."""

from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.procurement.models import POStatus, PRStatus
from apps.procurement.services import ProcurementService
from apps.parties.models import Party
from apps.rbac.services import seed_rbac_catalog
from apps.warehouse.access import can_mutate_warehouse
from apps.warehouse.models import SKU, Stock, StockMovement, StockMovementType, Warehouse
from apps.warehouse.services import (
    adjust_stock,
    apply_movement,
    create_sku,
    request_issue_line,
    update_sku,
)
from apps.core.services import DomainError

User = get_user_model()


class Phase4422SkuMasterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.client = Client()
        self.fm = User.objects.create_user(
            username="w4422-fm",
            email="w4422-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.desk = User.objects.create_user(
            username="w4422-desk",
            email="w4422-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.mgmt = User.objects.create_user(
            username="w4422-mgmt",
            email="w4422-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.wh = Warehouse.objects.create(code="MAIN4422", name="Main")

    def test_fm_creates_and_edits_sku(self):
        self.assertTrue(can_mutate_warehouse(self.fm))
        self.client.force_login(self.fm)
        form = self.client.get(reverse("erp:warehouse_sku_create"))
        self.assertEqual(form.status_code, 200)
        token = form.context["submit_token"]
        create = self.client.post(
            reverse("erp:warehouse_sku_create"),
            {
                "code": "bolt-10",
                "name": "Bolt M10",
                "unit": "pcs",
                "reorder_level": "5",
                "submit_token": token,
            },
        )
        self.assertEqual(create.status_code, 302)
        sku = SKU.objects.get(code="BOLT-10")
        self.assertEqual(sku.name, "Bolt M10")
        self.assertEqual(sku.reorder_level, Decimal("5"))
        self.assertTrue(AuditLog.objects.filter(action="warehouse.sku.create").exists())

        detail = self.client.get(reverse("erp:warehouse_sku_detail", kwargs={"code": sku.code}))
        self.assertEqual(detail.status_code, 200)
        upd = self.client.post(
            reverse("erp:warehouse_sku_detail", kwargs={"code": sku.code}),
            {
                "action": "update_sku",
                "name": "Bolt M10 Zinc",
                "unit": "pcs",
                "reorder_level": "8",
                "submit_token": "upd-1",
            },
        )
        self.assertEqual(upd.status_code, 302)
        sku.refresh_from_db()
        self.assertEqual(sku.name, "Bolt M10 Zinc")
        self.assertEqual(sku.reorder_level, Decimal("8"))

    def test_duplicate_sku_blocked(self):
        create_sku(code="DUP1", name="One", actor=self.fm)
        with self.assertRaises(DomainError):
            create_sku(code="dup1", name="Two", actor=self.fm)

    def test_negative_reorder_blocked(self):
        with self.assertRaises(DomainError):
            create_sku(code="NEG1", name="Bad", reorder_level="-1", actor=self.fm)

    def test_desk_and_mgmt_cannot_mutate(self):
        self.assertFalse(can_mutate_warehouse(self.desk))
        self.assertFalse(can_mutate_warehouse(self.mgmt))
        self.client.force_login(self.desk)
        resp = self.client.get(reverse("erp:warehouse_sku_create"))
        self.assertIn(resp.status_code, (302, 403))
        self.client.force_login(self.mgmt)
        page = self.client.get(reverse("erp:warehouse"))
        self.assertEqual(page.status_code, 200)
        denied = self.client.post(
            reverse("erp:warehouse"),
            {
                "action": "create_sku",
                "code": "MGMT1",
                "name": "Nope",
                "reorder_level": "1",
                "submit_token": "x",
            },
        )
        self.assertIn(denied.status_code, (302, 403))
        self.assertFalse(SKU.objects.filter(code="MGMT1").exists())

    def test_search_filter_and_pagination_context(self):
        for i in range(3):
            create_sku(code=f"SRCH{i}", name=f"Search item {i}", actor=self.fm)
        self.client.force_login(self.fm)
        resp = self.client.get(reverse("erp:warehouse"), {"q": "SRCH1"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "SRCH1")
        self.assertNotContains(resp, "SRCH0")


class Phase4422StockAdjustTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.client = Client()
        self.fm = User.objects.create_user(
            username="w4422-adj-fm",
            email="w4422-adj-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.sku = create_sku(code="ADJ1", name="Adjustable", reorder_level=2, actor=self.fm)
        self.wh = Warehouse.objects.create(code="ADJWH", name="Adj WH")

    def test_adjust_requires_reason_and_updates_balance(self):
        with self.assertRaises(DomainError):
            adjust_stock(
                sku=self.sku,
                warehouse=self.wh,
                new_quantity=10,
                reason="",
                actor=self.fm,
            )
        adjust_stock(
            sku=self.sku,
            warehouse=self.wh,
            new_quantity=12,
            reason="Cycle count",
            actor=self.fm,
        )
        stock = Stock.objects.get(sku=self.sku, warehouse=self.wh)
        self.assertEqual(stock.quantity, Decimal("12"))
        self.assertTrue(
            StockMovement.objects.filter(
                sku=self.sku, movement_type=StockMovementType.ADJUSTMENT, quantity=Decimal("12")
            ).exists()
        )
        self.assertTrue(AuditLog.objects.filter(action="warehouse.stock.adjust").exists())

    def test_sku_edit_does_not_change_stock(self):
        Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("7"))
        update_sku(self.sku, name="Renamed", unit="pcs", reorder_level=3, actor=self.fm)
        self.assertEqual(Stock.objects.get(sku=self.sku, warehouse=self.wh).quantity, Decimal("7"))

    def test_adjust_cannot_go_below_reserved(self):
        Stock.objects.create(
            sku=self.sku, warehouse=self.wh, quantity=Decimal("10"), reserved_quantity=Decimal("4")
        )
        with self.assertRaises(DomainError):
            adjust_stock(
                sku=self.sku,
                warehouse=self.wh,
                new_quantity=2,
                reason="bad",
                actor=self.fm,
            )


class Phase4422IssueReceiptTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.fm = User.objects.create_user(
            username="w4422-iss-fm",
            email="w4422-iss-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="w4422-iss-adm",
            email="w4422-iss-adm@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.sku = SKU.objects.create(code="ISS1", name="Issue item", unit="pcs", reorder_level=5)
        self.wh = Warehouse.objects.create(code="ISSWH", name="Issue WH")
        self.stock = Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("10"))
        self.wo = WorkOrder.objects.create(
            code="WO-4422-1",
            title="Material job",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )

    def test_issue_and_insufficient_stock(self):
        request_issue_line(
            work_order=self.wo,
            warehouse=self.wh,
            sku=self.sku,
            quantity=Decimal("3"),
            actor=self.fm,
        )
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, Decimal("3"))
        with self.assertRaises((ValueError, DomainError)):
            request_issue_line(
                work_order=self.wo,
                warehouse=self.wh,
                sku=self.sku,
                quantity=Decimal("20"),
                actor=self.fm,
            )

    def test_completed_wo_blocks_issue(self):
        self.wo.status = WorkOrderStatus.COMPLETED
        self.wo.save(update_fields=["status"])
        with self.assertRaises(DomainError):
            request_issue_line(
                work_order=self.wo,
                warehouse=self.wh,
                sku=self.sku,
                quantity=Decimal("1"),
                actor=self.fm,
            )

    def test_partial_receive_and_over_receive_blocked(self):
        self.stock.quantity = Decimal("1")
        self.stock.save(update_fields=["quantity"])
        pr = ProcurementService.create_pr_from_low_stock(stock=self.stock, requested_by=self.fm)
        # Admin bypasses FM approval-limit fail-closed path for receive coverage.
        ProcurementService.approve_pr(pr, actor=self.admin)
        from apps.parties.models import PartyRole, PartyRoleCode

        supplier = Party.objects.create(legal_name="Supplier 4422")
        PartyRole.objects.get_or_create(party=supplier, role=PartyRoleCode.SUPPLIER)
        po = ProcurementService.create_po_from_pr(pr, supplier_party=supplier)
        line = po.lines.get()
        half = max((line.qty or Decimal("2")) / 2, Decimal("1"))
        ProcurementService.receive_po(
            po, warehouse=self.wh, actor=self.fm, line_qtys={line.pk: half}
        )
        po.refresh_from_db()
        self.assertEqual(po.status, POStatus.PARTIAL)
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(
                po,
                warehouse=self.wh,
                actor=self.fm,
                line_qtys={line.pk: (line.qty or 0) + Decimal("100")},
            )

    def test_low_stock_pr_dedupe_and_sku(self):
        self.stock.quantity = Decimal("1")
        self.stock.save(update_fields=["quantity"])
        pr1 = ProcurementService.create_pr_from_low_stock(stock=self.stock, requested_by=self.fm)
        pr2 = ProcurementService.create_pr_from_low_stock(stock=self.stock, requested_by=self.fm)
        self.assertEqual(pr1.pk, pr2.pk)
        self.assertEqual(pr1.lines.get().sku_id, self.sku.pk)
        self.assertEqual(pr1.status, PRStatus.SUBMITTED)


@override_settings(DEBUG=True)
class Phase4422ConcurrentIssueTests(TransactionTestCase):
    """Real PostgreSQL concurrent reservation — only meaningful outside nested TestCase txn."""

    def setUp(self):
        seed_rbac_catalog()
        self.fm = User.objects.create_user(
            username="w4422-conc-fm",
            email="w4422-conc-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.sku = SKU.objects.create(code="CONC1", name="Concurrent", unit="pcs", reorder_level=0)
        self.wh = Warehouse.objects.create(code="CONCWH", name="Conc WH")
        Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("5"))
        self.wo_a = WorkOrder.objects.create(
            code="WO-CONC-A",
            title="A",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        self.wo_b = WorkOrder.objects.create(
            code="WO-CONC-B",
            title="B",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )

    def test_concurrent_reservations_do_not_overspend(self):
        if connection.vendor != "postgresql":
            self.skipTest("Concurrency evidence requires PostgreSQL")

        def reserve(wo, qty):
            try:
                request_issue_line(
                    work_order=wo,
                    warehouse=self.wh,
                    sku=self.sku,
                    quantity=Decimal(qty),
                    actor=self.fm,
                )
                return "ok"
            except Exception as exc:  # noqa: BLE001 — either side may lose the race
                return f"err:{exc}"

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(reserve, self.wo_a, "4"),
                pool.submit(reserve, self.wo_b, "4"),
            ]
            results = [f.result() for f in as_completed(futures)]

        stock = Stock.objects.get(sku=self.sku, warehouse=self.wh)
        # One may succeed fully; total reserved cannot exceed on-hand.
        self.assertLessEqual(stock.reserved_quantity, stock.quantity)
        self.assertTrue(any(r == "ok" for r in results))
        # Combined reserved + failures must not leave reserved > quantity
        self.assertLessEqual(stock.reserved_quantity, Decimal("5"))
