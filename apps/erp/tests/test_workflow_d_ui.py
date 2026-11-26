"""Workflow D operator UI closeout — Facility → WH → Procurement screens."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
from apps.maintenance.services import next_wo_code
from apps.parties.models import Party, PartyRole, PartyRoleCode
from apps.procurement.models import PurchaseOrder, PurchaseRequest
from apps.procurement.services import ProcurementService
from apps.procurement.tests.support import (
    approve_pending_commitment,
    approve_pr_via_management,
)
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.warehouse.models import SKU, Stock, Warehouse
from apps.warehouse.services import confirm_issue, request_issue_line

User = get_user_model()


class WorkflowDUICloseoutTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.admin = User.objects.create_user(
            username="wfd-ui-adm",
            email="wfd-ui-adm@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.fm = User.objects.create_user(
            username="wfd-ui-fm",
            email="wfd-ui-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(self.fm, "supply.head")
        self.wh = Warehouse.objects.create(code="WFDUI-WH", name="WFD UI WH")
        self.sku = SKU.objects.create(
            code="WFDUI-SKU", name="Filter", unit="ədəd", reorder_level=5
        )
        self.stock = Stock.objects.create(
            sku=self.sku, warehouse=self.wh, quantity=Decimal("1")
        )
        self.wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title="WFD UI filter job",
            status=WorkOrderStatus.OPEN,
            priority=WorkOrderPriority.NORMAL,
        )
        self.supplier_a = Party.objects.create(legal_name="WFDUI Supplier A")
        self.supplier_b = Party.objects.create(legal_name="WFDUI Supplier B")
        PartyRole.objects.get_or_create(party=self.supplier_a, role=PartyRoleCode.SUPPLIER)
        PartyRole.objects.get_or_create(party=self.supplier_b, role=PartyRoleCode.SUPPLIER)

    def test_low_stock_pr_rfq_compare_receive_issue_http(self):
        # Warehouse: low-stock → PR
        self.client.force_login(self.fm)
        create_pr = self.client.post(
            reverse("erp:warehouse"),
            {
                "action": "create_pr",
                "stock_id": str(self.stock.pk),
                "submit_token": "wfd-pr-1",
            },
        )
        self.assertEqual(create_pr.status_code, 302)
        pr = PurchaseRequest.objects.filter(lines__sku=self.sku).latest("id")

        # Process approval comes from Management only (Admin has no self-approval).
        approve_pr_via_management(pr, actor=self.admin)
        pr.refresh_from_db()
        self.assertEqual(pr.status, "approved")

        # RFQ + two quotes for compare
        self.client.force_login(self.fm)
        rfq_resp = self.client.post(
            reverse("erp:procurement_pr_detail", kwargs={"code": pr.code}),
            {"action": "create_rfq"},
        )
        self.assertEqual(rfq_resp.status_code, 302)
        rfq_code = rfq_resp.url.rstrip("/").split("/")[-1]
        rfq_url = reverse("erp:procurement_rfq_detail", kwargs={"code": rfq_code})

        self.client.post(
            rfq_url,
            {
                "action": "add_quote",
                "supplier_party_id": str(self.supplier_a.pk),
                "unit_price": "40",
                "lead_time_days": "5",
                "submit_token": "q1",
            },
        )
        self.client.post(
            rfq_url,
            {
                "action": "add_quote",
                "supplier_party_id": str(self.supplier_b.pk),
                "unit_price": "25",
                "lead_time_days": "3",
                "submit_token": "q2",
            },
        )
        compare = self.client.get(rfq_url)
        self.assertContains(compare, "ən ucuz")
        self.assertContains(compare, "Seç və PO yarat")
        self.assertContains(compare, "25")

        # Select cheapest — Admin has no local authority: escalates, no PO yet.
        from apps.procurement.models import RFQQuote

        cheap = RFQQuote.objects.filter(rfq__code=rfq_code, unit_price=Decimal("25")).get()
        self.client.force_login(self.admin)
        select = self.client.post(
            rfq_url,
            {"action": "select_quote", "quote_id": str(cheap.pk)},
        )
        self.assertEqual(select.status_code, 302)
        self.assertFalse(PurchaseOrder.objects.filter(pr=pr).exists())
        # Management approves the commitment, then the same UI action issues the PO.
        approve_pending_commitment(pr)
        select = self.client.post(
            rfq_url,
            {"action": "select_quote", "quote_id": str(cheap.pk)},
        )
        self.assertEqual(select.status_code, 302)
        po = PurchaseOrder.objects.get(pr=pr)
        self.assertEqual(po.supplier_party_id, self.supplier_b.pk)

        # After first PO consumes remaining qty, PR is ordered — no further PO create.
        pr.refresh_from_db()
        self.assertEqual(pr.status, "ordered")
        ordered_pr = self.client.get(
            reverse("erp:procurement_pr_detail", kwargs={"code": pr.code})
        )
        self.assertContains(ordered_pr, "Qalan sifariş")
        self.assertNotContains(ordered_pr, ">PO yarat<")
        ordered_rfq = self.client.get(rfq_url)
        self.assertContains(ordered_rfq, "ən ucuz")
        self.assertNotContains(ordered_rfq, "Seç və PO yarat")

        # Partial receive → restock
        line = po.lines.get()
        recv = self.client.post(
            reverse("erp:procurement_po_detail", kwargs={"code": po.code}),
            {
                "action": "receive_po",
                "receive_mode": "partial",
                "operation_key": uuid.uuid4().hex,
                "submit_token": "recv1",
                "warehouse_id": str(self.wh.pk),
                f"recv_qty_{line.pk}": "4",
            },
        )
        self.assertEqual(recv.status_code, 302)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("5"))

        # Issue restocked material to WO
        issue = request_issue_line(
            work_order=self.wo,
            warehouse=self.wh,
            sku=self.sku,
            quantity=Decimal("2"),
            actor=self.fm,
        )
        confirm_issue(
            issue,
            actor=self.fm,
            lines=[{"id": issue.lines.get().pk, "issued_qty": "2", "unit_cost": "25"}],
        )
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, Decimal("3"))

    def test_management_denied_procurement_edit(self):
        mgmt = User.objects.create_user(
            username="wfd-ui-mgmt",
            email="wfd-ui-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        pr = ProcurementService.create_pr_for_work_order(
            self.wo, actor=self.fm, description="x", qty="1", sku=self.sku
        )
        approve_pr_via_management(pr, actor=self.admin)
        self.client.force_login(mgmt)
        page = self.client.get(reverse("erp:procurement_pr_detail", kwargs={"code": pr.code}))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "PO yarat")
