"""Targeted Supply portal consolidation checks (explicit labels only)."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.maintenance.models import WorkOrder, WorkOrderStatus
from apps.procurement.models import POStatus, PRStatus, PurchaseOrder, PurchaseRequest, PRSource
from apps.procurement.services import ProcurementService
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.residents.models import ResidentCompany
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class SupplyPortalConsolidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.fm = User.objects.create_user(
            username="supply-fm",
            email="supply-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.desk = User.objects.create_user(
            username="supply-desk",
            email="supply-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.mgmt = User.objects.create_user(
            username="supply-mgmt",
            email="supply-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        cls.sales = User.objects.create_user(
            username="supply-sales",
            email="supply-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        # Head grant is explicit — not every FM.
        grant_user_permission(cls.fm, "supply.head")
        cls.company = ResidentCompany.objects.create(
            name="Supply Co",
            slug="supply-co",
            contact_person_name="Aysel",
            contact_person_position="Ofis meneceri",
            contact_person_phone="+994501112233",
            contact_person_email="aysel@supply.co",
        )

    def test_landing_routes_to_supply_portal(self):
        for user in (self.fm, self.desk):
            c = Client()
            c.force_login(user)
            r = c.get(reverse("erp:dashboard"))
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r.url, reverse("erp:supply_dashboard"))

    def test_facility_redirect_preserves_supply_portal(self):
        c = Client()
        c.force_login(self.fm)
        r = c.get(reverse("erp:facility_dashboard"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("erp:supply_dashboard"))
        board = c.get(reverse("erp:supply_dashboard"))
        self.assertEqual(board.status_code, 200)
        self.assertContains(board, "Təchizat şöbəsi")

    def test_head_grant_is_explicit_not_every_fm(self):
        other = User.objects.create_user(
            username="other-fm",
            email="other-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        from apps.rbac.services import user_has_permission

        self.assertTrue(user_has_permission(self.fm, "supply.head"))
        self.assertFalse(user_has_permission(other, "supply.head"))

    def test_deny_unapproved_small_purchase(self):
        pr = PurchaseRequest.objects.create(
            code="PR-SUP-1",
            title="Kiçik ehtiyat",
            status=PRStatus.APPROVED,
            requested_by=self.fm,
            source=PRSource.WO,
        )
        from apps.procurement.models import PRLine

        PRLine.objects.create(pr=pr, description="Bolt", qty=Decimal("2"), unit="pcs")
        from apps.parties.models import Party, PartyRole, PartyRoleCode

        supplier = Party.objects.create(legal_name="Sup A")
        PartyRole.objects.get_or_create(party=supplier, role=PartyRoleCode.SUPPLIER)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr,
                supplier_party=supplier,
                actor=self.fm,
                unit_price=Decimal("5.00"),
            )

    def test_changed_terms_after_approval_require_new_commitment(self):
        pr = PurchaseRequest.objects.create(
            code="PR-SUP-2",
            title="Qiymət dəyişikliyi",
            status=PRStatus.APPROVED,
            requested_by=self.fm,
            source=PRSource.WO,
        )
        from apps.procurement.models import PRLine
        from apps.parties.models import Party, PartyRole, PartyRoleCode

        PRLine.objects.create(pr=pr, description="Kabel", qty=Decimal("1"), unit="pcs")
        supplier = Party.objects.create(legal_name="Sup B")
        PartyRole.objects.get_or_create(party=supplier, role=PartyRoleCode.SUPPLIER)
        assessed = ProcurementService._priced_assessment(pr, Decimal("10.00"))
        pending = ProcurementService.escalate_commitment_for_management(
            pr,
            assessed=assessed,
            actor=self.fm,
            unit_price=Decimal("10.00"),
            supplier_id=supplier.pk,
            reason="over_limit",
        )
        ApprovalService.decide(pending, approved=True, decided_by=self.mgmt)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr,
                supplier_party=supplier,
                actor=self.fm,
                unit_price=Decimal("25.00"),
            )

    def test_unauthorized_directory_denied(self):
        c = Client()
        c.force_login(self.sales)
        # Sales has resident.view in matrix historically — revoke directory via role without directory
        from apps.rbac.models import RolePermission
        from apps.rbac.models import PermissionCode

        perm = PermissionCode.objects.filter(code="resident.directory.view").first()
        if perm:
            RolePermission.objects.filter(
                role=Role.SALES, permission=perm
            ).delete()
        # Sales still has resident.view; directory helper allows some roles with resident.view.
        # Use a reception-less accountant-like denial: create user without directory/view.
        outsider = User.objects.create_user(
            username="no-dir",
            email="no-dir@test.az",
            password="x",
            role=Role.SECURITY,
            is_staff=True,
        )
        c.force_login(outsider)
        r = c.get(reverse("erp:resident_directory"))
        self.assertIn(r.status_code, (302, 403))
        detail = c.get(reverse("erp:resident_directory_detail", args=[self.company.slug]))
        self.assertIn(detail.status_code, (302, 403))

    def test_directory_visible_fields_for_supply(self):
        c = Client()
        c.force_login(self.desk)
        r = c.get(reverse("erp:resident_directory"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Supply Co")
        self.assertContains(r, "Aysel")
        self.assertContains(r, "Ofis meneceri")
        detail = c.get(reverse("erp:resident_directory_detail", args=[self.company.slug]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "aysel@supply.co")
        self.assertNotContains(detail, "IBAN")

    def test_open_fm_work_order_still_accessible(self):
        wo = WorkOrder.objects.create(
            code="WO-SUP-OPEN",
            title="Açıq təmir",
            status=WorkOrderStatus.OPEN,
        )
        c = Client()
        c.force_login(self.fm)
        r = c.get(reverse("erp:work_order_detail", kwargs={"code": wo.code}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "WO-SUP-OPEN")

    def test_journey_stock_issue_complete_repair(self):
        from apps.maintenance.services import WorkOrderService, assign_work_order
        from apps.warehouse.models import SKU, Stock, Warehouse
        from apps.warehouse.services import confirm_issue, request_issue_line

        wh = Warehouse.objects.create(code="WH-SUP", name="Supply WH")
        sku = SKU.objects.create(code="SKU-SPARE", name="Spare", unit="pcs")
        Stock.objects.create(warehouse=wh, sku=sku, quantity=Decimal("10"))
        wo = WorkOrder.objects.create(code="WO-SUP-STOCK", title="Təmir ehtiyat", status=WorkOrderStatus.OPEN)
        assign_work_order(wo, actor=self.fm, assignee_id=self.desk.pk)
        issue = request_issue_line(
            work_order=wo, warehouse=wh, sku=sku, quantity=Decimal("2"), actor=self.fm
        )
        confirm_issue(
            issue,
            actor=self.fm,
            lines=[{"id": issue.lines.get().pk, "issued_qty": "2", "unit_cost": "1"}],
        )
        WorkOrderService.set_status(wo, WorkOrderStatus.COMPLETED, actor=self.fm)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrderStatus.COMPLETED)

    def test_journey_purchase_partial_receipt_issue(self):
        from apps.parties.models import Party, PartyRole, PartyRoleCode
        from apps.procurement.models import PRLine
        from apps.warehouse.models import SKU, Warehouse
        from apps.warehouse.services import confirm_issue, request_issue_line

        wh = Warehouse.objects.create(code="WH-SUP2", name="Supply WH2")
        sku = SKU.objects.create(code="SKU-BUY", name="Buy part", unit="pcs")
        wo = WorkOrder.objects.create(code="WO-SUP-BUY", title="Material yox", status=WorkOrderStatus.OPEN)
        pr = PurchaseRequest.objects.create(
            code="PR-SUP-BUY",
            title="Material",
            status=PRStatus.APPROVED,
            requested_by=self.fm,
            source=PRSource.WO,
            work_order=wo,
        )
        PRLine.objects.create(pr=pr, description="Buy part", sku=sku, qty=Decimal("4"), unit="pcs")
        supplier = Party.objects.create(legal_name="Sup Buy")
        PartyRole.objects.get_or_create(party=supplier, role=PartyRoleCode.SUPPLIER)
        assessed = ProcurementService._priced_assessment(pr, Decimal("12.00"))
        pending = ProcurementService.escalate_commitment_for_management(
            pr,
            assessed=assessed,
            actor=self.fm,
            unit_price=Decimal("12.00"),
            supplier_id=supplier.pk,
            reason="over_limit",
        )
        ApprovalService.decide(pending, approved=True, decided_by=self.mgmt)
        po = ProcurementService.create_po_from_pr(
            pr,
            supplier_party=supplier,
            actor=self.fm,
            unit_price=Decimal("12.00"),
        )
        self.assertEqual(po.status, POStatus.SENT)
        half = {po.lines.first().pk: Decimal("2")}
        ProcurementService.receive_po(po, warehouse=wh, actor=self.fm, line_qtys=half)
        po.refresh_from_db()
        self.assertEqual(po.status, POStatus.PARTIAL)
        issue = request_issue_line(
            work_order=wo, warehouse=wh, sku=sku, quantity=Decimal("1"), actor=self.fm
        )
        confirm_issue(
            issue,
            actor=self.fm,
            lines=[{"id": issue.lines.get().pk, "issued_qty": "1", "unit_cost": "12"}],
        )

    def test_self_approval_blocked(self):
        from django.contrib.contenttypes.models import ContentType

        pr = PurchaseRequest.objects.create(
            code="PR-SUP-SELF",
            title="Self",
            status=PRStatus.SUBMITTED,
            requested_by=self.fm,
            source=PRSource.WO,
        )
        ct = ContentType.objects.get_for_model(PurchaseRequest)
        req = ApprovalRequest.objects.create(
            workflow_code="procurement.commitment",
            status=ApprovalStatus.PENDING,
            requested_by=self.fm,
            entity_type=ct,
            entity_id=pr.pk,
            payload={},
        )
        with self.assertRaises(DomainError):
            ApprovalService.decide(req, approved=True, decided_by=self.fm)

    def test_set_line_price_blocked_after_issue(self):
        from apps.parties.models import Party, PartyRole, PartyRoleCode
        from apps.procurement.models import PRLine

        pr = PurchaseRequest.objects.create(
            code="PR-SUP-PRICE",
            title="Qiymət qoruma",
            status=PRStatus.APPROVED,
            requested_by=self.fm,
            source=PRSource.WO,
        )
        PRLine.objects.create(pr=pr, description="Part", qty=Decimal("1"), unit="pcs")
        supplier = Party.objects.create(legal_name="Sup Price")
        PartyRole.objects.get_or_create(party=supplier, role=PartyRoleCode.SUPPLIER)
        assessed = ProcurementService._priced_assessment(pr, Decimal("8.00"))
        pending = ProcurementService.escalate_commitment_for_management(
            pr,
            assessed=assessed,
            actor=self.fm,
            unit_price=Decimal("8.00"),
            supplier_id=supplier.pk,
            reason="over_limit",
        )
        ApprovalService.decide(pending, approved=True, decided_by=self.mgmt)
        po = ProcurementService.create_po_from_pr(
            pr, supplier_party=supplier, actor=self.fm, unit_price=Decimal("8.00")
        )
        self.assertEqual(po.status, POStatus.SENT)
        line = po.lines.get()
        with self.assertRaises(DomainError):
            ProcurementService.set_po_line_unit_price(
                line, unit_price=Decimal("99.00"), actor=self.fm
            )

    def test_desk_has_facility_powers_hides_leases_nav(self):
        """Unified Təchizat role owns facility spaces; leases stay out of sidebar."""
        from apps.rbac.services import user_has_permission

        grant_user_permission(self.desk, "supply.head")
        self.assertTrue(user_has_permission(self.desk, "supply.head"))
        self.assertTrue(user_has_permission(self.desk, "procurement.edit"))
        self.assertTrue(user_has_permission(self.desk, "space.edit"))
        c = Client()
        c.force_login(self.desk)
        r = c.get(reverse("erp:spaces"))
        self.assertEqual(r.status_code, 200)
        from apps.accounts.nav import build_nav_flags

        flags = build_nav_flags(self.desk)
        self.assertTrue(flags["nav_property"])
        self.assertFalse(flags["nav_leases"])
