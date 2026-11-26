"""Phase 4.4.2.3 — Manual PR, suppliers, PO+supplier, RFQ UI, approval source rules."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.core.services import DomainError
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus
from apps.procurement.models import PRSource, PRStatus, PurchaseApprovalLimit, PurchaseOrder, PurchaseRequest
from apps.procurement.services import ProcurementService
from apps.procurement.tests.support import (
    approve_pr_via_management,
    issue_priced_po,
    issue_quote_po,
)
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.warehouse.models import SKU, Stock, Warehouse

User = get_user_model()


class Phase4423ManualPRTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.client = Client()
        self.fm = User.objects.create_user(
            username="p4423-fm", email="p4423-fm@test.az", password="x", role=Role.SERVICE_DESK, is_staff=True
        )
        grant_user_permission(self.fm, "supply.head")
        self.admin = User.objects.create_user(
            username="p4423-adm",
            email="p4423-adm@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.mgmt = User.objects.create_user(
            username="p4423-mgmt", email="p4423-mgmt@test.az", password="x", role=Role.MANAGEMENT, is_staff=True
        )
        self.acct = User.objects.create_user(
            username="p4423-acct", email="p4423-acct@test.az", password="x", role=Role.ACCOUNTANT, is_staff=True
        )
        self.sku = SKU.objects.create(code="P4423-A", name="Item A", unit="pcs", reorder_level=1)
        PurchaseApprovalLimit.objects.update_or_create(
            role=Role.SERVICE_DESK, defaults={"max_amount": Decimal("100"), "is_active": True}
        )

    def test_manual_pr_create_via_ui(self):
        self.client.force_login(self.fm)
        form = self.client.get(reverse("erp:procurement_pr_create"))
        self.assertEqual(form.status_code, 200)
        token = form.context["submit_token"]
        resp = self.client.post(
            reverse("erp:procurement_pr_create"),
            {
                "title": "Office supplies",
                "notes": "Monthly restock",
                "source": "wo",  # spoof attempt — ignored
                "submit_token": token,
                "line_description_0": "Paper A4",
                "line_qty_0": "10",
                "line_unit_0": "pcs",
                "line_sku_0": str(self.sku.pk),
            },
        )
        self.assertEqual(resp.status_code, 302)
        pr = PurchaseRequest.objects.get(title="Office supplies")
        self.assertEqual(pr.source, PRSource.MANUAL)
        self.assertEqual(pr.requested_by_id, self.fm.pk)
        self.assertEqual(pr.status, PRStatus.SUBMITTED)
        self.assertEqual(pr.lines.count(), 1)
        self.assertEqual(pr.lines.get().sku_id, self.sku.pk)
        self.assertTrue(AuditLog.objects.filter(action="procurement.pr.create_manual").exists())

        # Duplicate token does not create another PR
        before = PurchaseRequest.objects.count()
        self.client.post(
            reverse("erp:procurement_pr_create"),
            {
                "title": "Office supplies",
                "notes": "Monthly restock",
                "submit_token": token,
                "line_description_0": "Paper A4",
                "line_qty_0": "10",
            },
        )
        self.assertEqual(PurchaseRequest.objects.count(), before)

    def test_empty_and_invalid_lines_rejected(self):
        with self.assertRaises(DomainError):
            ProcurementService.create_manual_pr(actor=self.fm, title="X", lines=[])
        with self.assertRaises(DomainError):
            ProcurementService.create_manual_pr(
                actor=self.fm, title="X", lines=[{"description": "a", "qty": "0"}]
            )

    def test_fm_cannot_approve_manual_pr(self):
        pr = ProcurementService.create_manual_pr(
            actor=self.fm,
            title="Manual deny",
            lines=[{"description": "x", "qty": "1"}],
        )
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.fm)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.SUBMITTED)

        # Admin cannot self-approve MANUAL either — Management must decide.
        with self.assertRaises(DomainError):
            ProcurementService.approve_pr(pr, actor=self.admin)
        pr.refresh_from_db()
        self.assertEqual(pr.status, PRStatus.SUBMITTED)

        approve_pr_via_management(pr, actor=self.admin)
        self.assertEqual(pr.status, PRStatus.APPROVED)

    def test_accountant_cannot_create_pr(self):
        self.client.force_login(self.acct)
        resp = self.client.get(reverse("erp:procurement_pr_create"))
        self.assertIn(resp.status_code, (302, 403))
        self.client.force_login(self.mgmt)
        denied = self.client.post(
            reverse("erp:procurement"),
            {"action": "create_po", "pr_id": "1", "supplier_party_id": "1"},
        )
        # Management lacks procurement.edit — soft deny / redirect
        self.assertIn(denied.status_code, (302, 403))


class Phase4423SupplierTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.client = Client()
        self.fm = User.objects.create_user(
            username="p4423-sup-fm",
            email="p4423-sup-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(self.fm, "supply.head")
        self.residents_before = ResidentCompany.objects.count()

    def test_supplier_create_edit_and_no_resident_company(self):
        self.client.force_login(self.fm)
        form = self.client.get(reverse("erp:procurement_supplier_create"))
        self.assertEqual(form.status_code, 200)
        token = form.context["submit_token"]
        resp = self.client.post(
            reverse("erp:procurement_supplier_create"),
            {
                "legal_name": "Alpha Supply MMC",
                "tax_id": "1234567891",
                "contact_email": "a@test.az",
                "status": PartyStatus.ACTIVE,
                "submit_token": token,
            },
        )
        self.assertEqual(resp.status_code, 302)
        party = Party.objects.get(legal_name="Alpha Supply MMC")
        self.assertTrue(party.roles.filter(role=PartyRoleCode.SUPPLIER).exists())
        self.assertEqual(ResidentCompany.objects.count(), self.residents_before)

        with self.assertRaises(DomainError):
            ProcurementService.create_or_update_supplier(
                actor=self.fm, legal_name="Alpha Supply MMC", tax_id="999"
            )

        edit = self.client.post(
            reverse("erp:procurement_supplier_edit", kwargs={"pk": party.pk}),
            {
                "legal_name": "Alpha Supply MMC",
                "brand_name": "Alpha",
                "tax_id": "1234567891",
                "contact_phone": "+99450",
                "status": PartyStatus.ACTIVE,
                "submit_token": "edit-1",
            },
        )
        self.assertEqual(edit.status_code, 302)
        party.refresh_from_db()
        self.assertEqual(party.brand_name, "Alpha")


class Phase4423POAndRFQTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()

    def setUp(self):
        self.client = Client()
        self.fm = User.objects.create_user(
            username="p4423-po-fm",
            email="p4423-po-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(self.fm, "supply.head")
        self.admin = User.objects.create_user(
            username="p4423-po-adm",
            email="p4423-po-adm@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.sku = SKU.objects.create(code="P4423-B", name="Item B", unit="pcs", reorder_level=0)
        self.wh = Warehouse.objects.create(code="P4423WH", name="P WH")
        Stock.objects.create(sku=self.sku, warehouse=self.wh, quantity=Decimal("1"))
        self.supplier = Party.objects.create(legal_name="Beta Supplier")
        PartyRole.objects.get_or_create(party=self.supplier, role=PartyRoleCode.SUPPLIER)

    def test_po_requires_supplier_and_receive(self):
        pr = ProcurementService.create_manual_pr(
            actor=self.admin,
            title="Need parts",
            lines=[{"description": "Bolt", "qty": "4", "sku_id": self.sku.pk}],
        )
        approve_pr_via_management(pr, actor=self.admin)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(pr, supplier_party=None, actor=self.admin)
        po = issue_priced_po(pr, supplier=self.supplier, unit_price="10", actor=self.admin)
        self.assertEqual(po.supplier_party_id, self.supplier.pk)
        before = Stock.objects.get(sku=self.sku, warehouse=self.wh).quantity
        ProcurementService.receive_po(po, warehouse=self.wh, actor=self.admin)
        stock = Stock.objects.get(sku=self.sku, warehouse=self.wh)
        self.assertEqual(stock.quantity, before + Decimal("4"))
        po.refresh_from_db()
        self.assertEqual(po.status, "received")
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(po, warehouse=self.wh, actor=self.admin)

    def test_rfq_quote_select_creates_po(self):
        pr = ProcurementService.create_manual_pr(
            actor=self.admin,
            title="RFQ path",
            lines=[{"description": "Valve", "qty": "2", "sku_id": self.sku.pk}],
        )
        approve_pr_via_management(pr, actor=self.admin)
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.admin)
        quote = ProcurementService.add_rfq_quote(
            rfq, supplier_party=self.supplier, unit_price="15.50", actor=self.admin
        )
        po = issue_quote_po(quote, actor=self.admin)
        self.assertEqual(po.supplier_party_id, self.supplier.pk)
        self.assertEqual(po.lines.get().unit_price, Decimal("15.50"))
        quote.refresh_from_db()
        self.assertTrue(quote.is_selected)

    def test_ui_create_po_with_supplier(self):
        pr = ProcurementService.create_manual_pr(
            actor=self.admin,
            title="UI PO",
            lines=[{"description": "x", "qty": "1", "sku_id": self.sku.pk}],
        )
        approve_pr_via_management(pr, actor=self.admin)
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("erp:procurement_pr_detail", kwargs={"code": pr.code}),
            {
                "action": "create_po",
                "supplier_party_id": str(self.supplier.pk),
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(PurchaseOrder.objects.filter(pr=pr, supplier_party=self.supplier).exists())
