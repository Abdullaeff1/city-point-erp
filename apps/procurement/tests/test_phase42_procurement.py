"""Phase 4.2.3 — WO shortage→PR, approval limits, receive, warehouse confirm ACL."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.maintenance.services import next_wo_code
from apps.procurement.models import PRStatus, PurchaseApprovalLimit, PurchaseRequest
from apps.procurement.services import ProcurementService
from apps.procurement.tests.support import approve_pr_via_management, issue_priced_po
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.warehouse.models import SKU, Stock, Warehouse
from apps.warehouse.services import can_confirm_warehouse_issue, request_issue_line
from apps.workflows.models import ApprovalRequest, ApprovalStatus

User = get_user_model()


class Phase42ProcurementWarehouseTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.admin = User.objects.create_user(
            username="p42w-admin",
            email="p42w-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.fm = User.objects.create_user(
            username="p42w-fm",
            email="p42w-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(self.fm, "supply.head")
        self.mgmt = User.objects.create_user(
            username="p42w-mgmt",
            email="p42w-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.wh = Warehouse.objects.create(code="P42W", name="P42 WH")
        self.sku = SKU.objects.create(code="P42-SKU", name="Bolt", unit="ədəd", reorder_level=10)
        self.stock = Stock.objects.create(
            sku=self.sku, warehouse=self.wh, quantity=Decimal("2"), reserved_quantity=Decimal("0")
        )
        self.wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="P42 WO",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK,
            defaults={"max_amount": Decimal("1000"), "is_active": True},
        )

    def test_fm_can_confirm_issue_mgmt_cannot(self):
        self.assertTrue(can_confirm_warehouse_issue(self.fm))
        self.assertTrue(can_confirm_warehouse_issue(self.admin))
        self.assertFalse(can_confirm_warehouse_issue(self.mgmt))

    def test_shortage_creates_pr_with_sku(self):
        self.client.force_login(self.fm)
        from apps.maintenance.access import can_mutate_work_order

        self.assertTrue(can_mutate_work_order(self.fm, self.wo))
        resp = self.client.post(
            reverse("erp:work_order_detail", kwargs={"code": self.wo.code}),
            {
                "action": "issue",
                "sku": self.sku.pk,
                "warehouse": self.wh.pk,
                "quantity": "5",
                "create_pr_on_shortage": "1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        pr = PurchaseRequest.objects.filter(work_order=self.wo, source="wo").first()
        self.assertIsNotNone(pr)
        line = pr.lines.first()
        self.assertEqual(line.sku_id, self.sku.pk)
        self.assertEqual(line.qty, Decimal("5"))

    def test_unpriced_pr_escalates_not_qty_as_azn(self):
        """PR lines have no unit price — FM cannot treat qty as AZN spending."""
        pr_small = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="small", qty="2", sku=self.sku
        )
        with self.assertRaises(DomainError) as ctx:
            ProcurementService.approve_pr(pr_small, actor=self.fm)
        self.assertIn("müəyyən edilməyib", str(ctx.exception))
        pr_small.refresh_from_db()
        self.assertEqual(pr_small.status, PRStatus.SUBMITTED)
        req = ApprovalRequest.objects.get(
            workflow_code="procurement.pr",
            status=ApprovalStatus.PENDING,
            entity_id=pr_small.pk,
        )
        self.assertEqual(req.payload.get("amount"), "")
        self.assertEqual(req.payload.get("currency"), "")
        self.assertEqual(req.payload.get("escalation_reason"), "amount_unknown")
        self.assertNotEqual(req.payload.get("amount"), "2")

        from apps.workflows.services import ApprovalService

        ApprovalService.decide(req, approved=True, decided_by=self.mgmt, comment="ok")
        ProcurementService.apply_management_pr_decision(pr_small, approved=True, actor=self.mgmt)
        pr_small.refresh_from_db()
        self.assertEqual(pr_small.status, PRStatus.APPROVED)

    def test_missing_limit_still_escalates_unpriced(self):
        PurchaseApprovalLimit.objects.filter(role=Role.SERVICE_DESK).delete()
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="no-limit", qty="1", sku=self.sku
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.SUBMITTED)
        pending = ApprovalRequest.objects.filter(
            workflow_code="procurement.pr", status=ApprovalStatus.PENDING, entity_id=pr.pk
        )
        self.assertEqual(pending.count(), 1)
        self.assertEqual(pending.get().payload.get("escalation_reason"), "amount_unknown")
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        self.assertEqual(pending.count(), 1)

    def test_fm_self_approval_blocked_without_price(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="self", qty="1", sku=self.sku
        )
        self.assertEqual(pr.requested_by_id, self.fm.pk)
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)

    def test_receive_po_updates_stock(self):
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.admin, description="recv", qty="3", sku=self.sku
        )
        approve_pr_via_management(pr, actor=self.admin)
        from apps.parties.models import Party, PartyRole, PartyRoleCode

        supplier = Party.objects.create(legal_name="Phase42 Supplier")
        PartyRole.objects.get_or_create(party=supplier, role=PartyRoleCode.SUPPLIER)
        po = issue_priced_po(pr, supplier=supplier, unit_price="5", actor=self.admin)
        before = Stock.objects.get(pk=self.stock.pk).quantity
        ProcurementService.receive_po(po, warehouse=self.wh, actor=self.admin)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, before + Decimal("3"))
        po.refresh_from_db()
        self.assertEqual(po.status, "received")
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(po, warehouse=self.wh, actor=self.admin)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, before + Decimal("3"))

    def test_reserve_when_stock_sufficient(self):
        issue = request_issue_line(
            work_order=self.wo,
            sku=self.sku,
            warehouse=self.wh,
            quantity=Decimal("1"),
            actor=self.fm,
        )
        self.assertIsNotNone(issue)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, Decimal("1"))
