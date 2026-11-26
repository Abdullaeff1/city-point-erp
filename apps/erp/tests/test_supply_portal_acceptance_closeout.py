"""Supply portal acceptance closeout — missing behaviors only (explicit labels)."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role
from apps.comms.models import Notification
from apps.core.services import DomainError
from apps.maintenance.models import WorkOrder, WorkOrderStatus
from apps.maintenance.services import WorkOrderService, assign_work_order, facility_work_order_assignees
from apps.parties.models import Party, PartyRole, PartyRoleCode
from apps.procurement.models import POStatus, PRLine, PRStatus, PurchaseOrder, PurchaseRequest, PRSource
from apps.procurement.services import WF_PROCUREMENT_COMMITMENT, ProcurementService
from apps.property.models import Building, Floor, Space
from apps.rbac.services import grant_user_permission, seed_rbac_catalog, user_has_permission
from apps.residents.models import ResidentCompany
from apps.warehouse.models import SKU, Stock, Warehouse
from apps.warehouse.services import can_confirm_warehouse_issue, confirm_issue, request_issue_line
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


@override_settings(PROCUREMENT_QUOTE_VAT_RATE="0.18")
class SupplyPortalAcceptanceCloseoutTests(TestCase):
    """Roles under test mirror production cutover: desk=head, SD staff, legacy FM, Mgmt."""

    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.head = User.objects.create_user(
            username="close-head",
            email="close-head@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(cls.head, "supply.head")
        cls.staff_sd = User.objects.create_user(
            username="close-sd",
            email="close-sd@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.legacy_fm = User.objects.create_user(
            username="close-fm",
            email="close-fm@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.mgmt = User.objects.create_user(
            username="close-mgmt",
            email="close-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        cls.company = ResidentCompany.objects.create(
            name="Twin Office Co",
            slug="twin-office-co",
            contact_person_name="Leyla",
            contact_person_position="Ofis koordinatoru",
            contact_person_phone="+994501234567",
            contact_person_email="leyla@twin.az",
            iban="AZ21NABZ00000000137010001944",
            bank_name="Secret Bank",
            legal_address="Hidden Legal St",
        )
        building = Building.objects.create(code="TOB", name="Twin Bldg")
        f1 = Floor.objects.create(building=building, code="3", name="3-cu mertebe")
        f2 = Floor.objects.create(building=building, code="5", name="5-ci mertebe")
        Space.objects.create(code="TO-301", name="Ofis 301", floor=f1, resident=cls.company)
        Space.objects.create(code="TO-501", name="Ofis 501", floor=f2, resident=cls.company)
        cls.wh = Warehouse.objects.create(code="CLOSE-WH", name="Close WH")
        cls.sku = SKU.objects.create(code="CLOSE-SKU", name="Filter", unit="pcs")
        Stock.objects.create(warehouse=cls.wh, sku=cls.sku, quantity=Decimal("20"))
        cls.sup_a = Party.objects.create(legal_name="Close Sup A")
        cls.sup_b = Party.objects.create(legal_name="Close Sup B")
        for p in (cls.sup_a, cls.sup_b):
            PartyRole.objects.get_or_create(party=p, role=PartyRoleCode.SUPPLIER)

    def test_effective_access_matrix_operations(self):
        """HTTP/service gates for head, ordinary SD, legacy FM, Management."""
        # Permissions snapshot
        self.assertTrue(user_has_permission(self.head, "supply.head"))
        self.assertTrue(user_has_permission(self.head, "procurement.edit"))  # implied
        self.assertTrue(user_has_permission(self.head, "warehouse.edit"))  # implied
        self.assertFalse(user_has_permission(self.head, "space.edit"))  # master data RO
        self.assertFalse(user_has_permission(self.staff_sd, "supply.head"))
        self.assertFalse(user_has_permission(self.staff_sd, "procurement.edit"))
        self.assertFalse(user_has_permission(self.staff_sd, "warehouse.edit"))
        # Non-head Təchizat: facility view yes; master-data / WH-PO mutate no.
        self.assertFalse(user_has_permission(self.legacy_fm, "supply.head"))
        self.assertFalse(user_has_permission(self.legacy_fm, "warehouse.edit"))
        self.assertFalse(user_has_permission(self.legacy_fm, "procurement.edit"))
        self.assertFalse(user_has_permission(self.legacy_fm, "procurement.approve"))
        self.assertTrue(user_has_permission(self.legacy_fm, "warehouse.view"))
        self.assertTrue(user_has_permission(self.legacy_fm, "space.view"))
        self.assertFalse(user_has_permission(self.legacy_fm, "space.edit"))
        self.assertFalse(user_has_permission(self.mgmt, "warehouse.edit"))
        self.assertFalse(user_has_permission(self.mgmt, "procurement.edit"))
        self.assertTrue(user_has_permission(self.mgmt, "approval.decide"))

        self.assertTrue(can_confirm_warehouse_issue(self.head))
        self.assertFalse(can_confirm_warehouse_issue(self.staff_sd))
        self.assertFalse(can_confirm_warehouse_issue(self.legacy_fm))
        self.assertFalse(can_confirm_warehouse_issue(self.mgmt))

        wo = WorkOrder.objects.create(code="WO-CLOSE-ACL", title="ACL", status=WorkOrderStatus.OPEN)
        # Ordinary SD cannot prepare/issue procurement
        with self.assertRaises(DomainError):
            ProcurementService.create_manual_pr(
                actor=self.staff_sd,
                title="SD blocked",
                lines=[{"description": "x", "qty": "1", "unit": "pcs"}],
            )
        # Head can prepare PR
        pr = ProcurementService.create_manual_pr(
            actor=self.head,
            title="Head prepare",
            lines=[{"description": "bolt", "qty": "1", "unit": "pcs", "sku_id": self.sku.pk}],
        )
        self.assertEqual(pr.status, PRStatus.SUBMITTED)
        # Management cannot edit procurement
        with self.assertRaises(DomainError):
            ProcurementService.create_manual_pr(
                actor=self.mgmt,
                title="Mgmt blocked",
                lines=[{"description": "x", "qty": "1", "unit": "pcs"}],
            )
        # Head stock issue
        issue = request_issue_line(
            work_order=wo, warehouse=self.wh, sku=self.sku, quantity=Decimal("1"), actor=self.head
        )
        confirm_issue(
            issue,
            actor=self.head,
            lines=[{"id": issue.lines.get().pk, "issued_qty": "1", "unit_cost": "2"}],
        )
        self.assertFalse(can_confirm_warehouse_issue(self.staff_sd))

        # Head cannot approve own commitment
        pr2 = PurchaseRequest.objects.create(
            code="PR-CLOSE-SELF",
            title="Self commit",
            status=PRStatus.APPROVED,
            requested_by=self.head,
            source=PRSource.MANUAL,
        )
        PRLine.objects.create(pr=pr2, description="x", qty=Decimal("1"), unit="pcs")
        assessed = ProcurementService._priced_assessment(pr2, Decimal("3.00"))
        pending = ProcurementService.escalate_commitment_for_management(
            pr2,
            assessed=assessed,
            actor=self.head,
            unit_price=Decimal("3.00"),
            supplier_id=self.sup_a.pk,
            reason="over_limit",
        )
        with self.assertRaises(DomainError):
            ApprovalService.decide(pending, approved=True, decided_by=self.head)
        # Management can approve; head can issue
        ApprovalService.decide(pending, approved=True, decided_by=self.mgmt)
        po = ProcurementService.create_po_from_pr(
            pr2,
            supplier_party=self.sup_a,
            actor=self.head,
            unit_price=Decimal("3.00"),
        )
        self.assertEqual(po.status, POStatus.SENT)
        # Legacy FM denied at service entry points (balances/records unchanged).
        pr_count_before = PurchaseRequest.objects.count()
        po_count_before = PurchaseOrder.objects.count()
        with self.assertRaises(DomainError):
            ProcurementService.create_manual_pr(
                actor=self.legacy_fm,
                title="FM blocked PR",
                lines=[{"description": "blocked", "qty": "1", "unit": "pcs"}],
            )
        pr3 = PurchaseRequest.objects.create(
            code="PR-CLOSE-FM",
            title="FM legacy",
            status=PRStatus.APPROVED,
            requested_by=self.head,
            source=PRSource.WO,
        )
        PRLine.objects.create(pr=pr3, description="y", qty=Decimal("1"), unit="pcs")
        assessed3 = ProcurementService._priced_assessment(pr3, Decimal("4.00"))
        pend3 = ProcurementService.escalate_commitment_for_management(
            pr3,
            assessed=assessed3,
            actor=self.head,
            unit_price=Decimal("4.00"),
            supplier_id=self.sup_b.pk,
            reason="over_limit",
        )
        ApprovalService.decide(pend3, approved=True, decided_by=self.mgmt)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr3,
                supplier_party=self.sup_b,
                actor=self.legacy_fm,
                unit_price=Decimal("4.00"),
            )
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(po, warehouse=self.wh, actor=self.legacy_fm)
        stock_before = Stock.objects.get(warehouse=self.wh, sku=self.sku).quantity
        with self.assertRaises(DomainError):
            request_issue_line(
                work_order=wo,
                warehouse=self.wh,
                sku=self.sku,
                quantity=Decimal("1"),
                actor=self.legacy_fm,
            )
        self.assertEqual(
            Stock.objects.get(warehouse=self.wh, sku=self.sku).quantity, stock_before
        )
        self.assertEqual(PurchaseRequest.objects.count(), pr_count_before + 1)
        self.assertEqual(PurchaseOrder.objects.count(), po_count_before)
        self.assertFalse(
            PurchaseOrder.objects.filter(pr=pr3, supplier_party=self.sup_b).exists()
        )

    def test_direct_po_consume_once_and_unpriced_draft_no_receive(self):
        pr = PurchaseRequest.objects.create(
            code="PR-CLOSE-DIR",
            title="Direct small",
            status=PRStatus.APPROVED,
            requested_by=self.head,
            source=PRSource.WO,
        )
        PRLine.objects.create(pr=pr, description="Part", qty=Decimal("2"), unit="pcs", sku=self.sku)
        assessed = ProcurementService._priced_assessment(pr, Decimal("7.00"))
        pending = ProcurementService.escalate_commitment_for_management(
            pr,
            assessed=assessed,
            actor=self.head,
            unit_price=Decimal("7.00"),
            supplier_id=self.sup_a.pk,
            reason="over_limit",
        )
        ApprovalService.decide(pending, approved=True, decided_by=self.mgmt)
        po = ProcurementService.create_po_from_pr(
            pr, supplier_party=self.sup_a, actor=self.head, unit_price=Decimal("7.00")
        )
        self.assertEqual(po.status, POStatus.SENT)
        # Retry must not create second PO (commitment consumed)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr, supplier_party=self.sup_a, actor=self.head, unit_price=Decimal("7.00")
            )
        self.assertEqual(PurchaseOrder.objects.filter(pr=pr).count(), 1)

        # Unpriced draft cannot receive
        pr_u = PurchaseRequest.objects.create(
            code="PR-CLOSE-UP",
            title="Unpriced",
            status=PRStatus.APPROVED,
            requested_by=self.head,
            source=PRSource.WO,
        )
        PRLine.objects.create(pr=pr_u, description="Draft part", qty=Decimal("1"), unit="pcs")
        draft = ProcurementService.create_po_from_pr(
            pr_u, supplier_party=self.sup_a, actor=self.head, unit_price=None
        )
        self.assertEqual(draft.status, POStatus.DRAFT)
        with self.assertRaises(DomainError):
            ProcurementService.receive_po(draft, warehouse=self.wh, actor=self.head)

    def test_split_award_supplier_a_approval_only_issues_a(self):
        from apps.procurement.models import QuoteLineResponseStatus, RFQDispatchChannel

        pr = ProcurementService.create_manual_pr(
            actor=self.head,
            title="Split AB",
            lines=[
                {"description": "Line1", "qty": "5", "unit": "pcs", "sku_id": self.sku.pk},
                {
                    "description": "Line2",
                    "qty": "5",
                    "unit": "pcs",
                    "sku_id": self.sku.pk,
                },
            ],
        )
        pr.status = PRStatus.APPROVED
        pr.save(update_fields=["status"])
        lines = list(pr.lines.order_by("id"))
        rfq = ProcurementService.create_rfq_from_pr(pr, actor=self.head)
        ProcurementService.invite_supplier_to_rfq(
            rfq,
            supplier_party=self.sup_a,
            line_specs=[{"pr_line_id": lines[0].pk}],
            actor=self.head,
            dispatch_channel=RFQDispatchChannel.MANUAL,
            mark_dispatched=True,
        )
        ProcurementService.invite_supplier_to_rfq(
            rfq,
            supplier_party=self.sup_b,
            line_specs=[{"pr_line_id": lines[1].pk}],
            actor=self.head,
            dispatch_channel=RFQDispatchChannel.MANUAL,
            mark_dispatched=True,
        )
        qa = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_a,
            actor=self.head,
            line_responses=[
                {
                    "pr_line_id": lines[0].pk,
                    "response_status": QuoteLineResponseStatus.QUOTED,
                    "unit_price": "10",
                    "qty": "5",
                }
            ],
        )
        qb = ProcurementService.add_rfq_quote_lines(
            rfq,
            supplier_party=self.sup_b,
            actor=self.head,
            line_responses=[
                {
                    "pr_line_id": lines[1].pk,
                    "response_status": QuoteLineResponseStatus.QUOTED,
                    "unit_price": "12",
                    "qty": "5",
                }
            ],
        )
        ProcurementService.award_pr_lines(
            pr,
            [
                {"pr_line_id": lines[0].pk, "quote_line_id": qa.lines.get().pk},
                {"pr_line_id": lines[1].pk, "quote_line_id": qb.lines.get().pk},
            ],
            actor=self.head,
        )
        outcomes = ProcurementService.create_pos_from_awards(pr, actor=self.head)
        by_sup = {o.supplier_id: o for o in outcomes}
        self.assertEqual(by_sup[self.sup_a.pk].status, "awaiting_financial_approval")
        self.assertEqual(by_sup[self.sup_b.pk].status, "awaiting_financial_approval")
        # Approve only supplier A commitment
        pend_a = ApprovalRequest.objects.filter(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            status=ApprovalStatus.PENDING,
            payload__supplier_id=self.sup_a.pk,
        ).latest("id")
        ApprovalService.decide(pend_a, approved=True, decided_by=self.mgmt)
        outcomes2 = ProcurementService.create_pos_from_awards(pr, actor=self.head)
        by2 = {o.supplier_id: o for o in outcomes2}
        self.assertEqual(by2[self.sup_a.pk].status, "issued")
        self.assertEqual(by2[self.sup_b.pk].status, "awaiting_financial_approval")
        self.assertEqual(
            PurchaseOrder.objects.filter(pr=pr, supplier_party=self.sup_a).count(), 1
        )
        self.assertFalse(
            PurchaseOrder.objects.filter(pr=pr, supplier_party=self.sup_b).exists()
        )
        # Retry must not duplicate A
        outcomes3 = ProcurementService.create_pos_from_awards(pr, actor=self.head)
        by3 = {o.supplier_id: o for o in outcomes3 if o.supplier_id}
        self.assertNotIn(self.sup_a.pk, by3)
        self.assertEqual(
            PurchaseOrder.objects.filter(pr=pr, supplier_party=self.sup_a).count(), 1
        )

    def test_changed_terms_require_fresh_approval_closeout(self):
        pr = PurchaseRequest.objects.create(
            code="PR-CLOSE-CHG",
            title="Terms change",
            status=PRStatus.APPROVED,
            requested_by=self.head,
            source=PRSource.WO,
        )
        PRLine.objects.create(pr=pr, description="Cable", qty=Decimal("1"), unit="pcs")
        assessed = ProcurementService._priced_assessment(pr, Decimal("9.00"))
        pending = ProcurementService.escalate_commitment_for_management(
            pr,
            assessed=assessed,
            actor=self.head,
            unit_price=Decimal("9.00"),
            supplier_id=self.sup_a.pk,
            reason="over_limit",
        )
        ApprovalService.decide(pending, approved=True, decided_by=self.mgmt)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr,
                supplier_party=self.sup_a,
                actor=self.head,
                unit_price=Decimal("40.00"),
            )

    def test_repair_directory_assign_complete_and_notify(self):
        from apps.core import events as bus
        from apps.core.event_handlers import _work_order_assigned_notify

        wo = WorkOrder.objects.create(
            code="WO-CLOSE-REP",
            title="Təmir twin",
            status=WorkOrderStatus.OPEN,
        )
        # Directory: one company, two offices, one card; no bank leak
        c = Client()
        c.force_login(self.head)
        listing = c.get(reverse("erp:resident_directory") + "?q=Twin")
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, "Twin Office Co", count=1)
        self.assertContains(listing, "3-cu mertebe")
        self.assertContains(listing, "5-ci mertebe")
        self.assertContains(listing, "Leyla")
        # Both offices on the same company card (not two company rows)
        self.assertEqual(listing.content.decode().count("twin-office-co"), 1)
        self.assertNotContains(listing, "AZ21NABZ")
        self.assertNotContains(listing, "Secret Bank")
        detail = c.get(reverse("erp:resident_directory_detail", args=[self.company.slug]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "leyla@twin.az")
        self.assertNotContains(detail, "IBAN")
        self.assertNotContains(detail, self.company.iban)
        self.assertNotContains(detail, "Hidden Legal")

        # Ordinary SD can open directory (resident.directory.view in matrix)
        c2 = Client()
        c2.force_login(self.staff_sd)
        self.assertEqual(c2.get(reverse("erp:resident_directory")).status_code, 200)

        # Assign + complete from Supply portal actors
        self.assertTrue(facility_work_order_assignees().filter(pk=self.head.pk).exists())
        assign_work_order(wo, actor=self.head, assignee_id=self.legacy_fm.pk)
        wo.refresh_from_db()
        self.assertEqual(wo.assigned_to_id, self.legacy_fm.pk)
        note = Notification.objects.filter(
            user=self.legacy_fm, event_key=f"wo.assigned.{wo.pk}.{self.legacy_fm.pk}"
        ).first()
        if note is None:
            _work_order_assigned_notify(
                bus.DomainEvent(
                    name=bus.WORK_ORDER_ASSIGNED,
                    payload={
                        "work_order_id": wo.pk,
                        "assignee_id": self.legacy_fm.pk,
                        "code": wo.code,
                    },
                    actor_id=self.head.pk,
                )
            )
            note = Notification.objects.filter(
                user=self.legacy_fm, event_key=f"wo.assigned.{wo.pk}.{self.legacy_fm.pk}"
            ).first()
        self.assertIsNotNone(note)
        WorkOrderService.set_status(wo, WorkOrderStatus.COMPLETED, actor=self.legacy_fm)
        wo.refresh_from_db()
        self.assertEqual(wo.status, WorkOrderStatus.COMPLETED)

    def test_head_grant_persists_in_userpermission_table(self):
        from apps.rbac.models import UserPermission

        self.assertTrue(
            UserPermission.objects.filter(
                user=self.head, permission__code="supply.head"
            ).exists()
        )
        # Survives "restart" simulation: re-fetch user, permission still effective
        head = User.objects.get(pk=self.head.pk)
        self.assertTrue(user_has_permission(head, "supply.head"))
        self.assertTrue(user_has_permission(head, "procurement.edit"))

    def test_reconcile_retires_property_fm_and_strips_sd_mutate_grants(self):
        """Legacy property_fm users remap; SERVICE_DESK never keeps supply mutate RolePermission."""
        from apps.rbac.models import PermissionCode, RolePermission, UserPermission
        from apps.rbac.services import (
            SUPPLY_MUTATIONS_NOT_ON_ROLE,
            reconcile_retired_property_fm_role,
            seed_rbac_catalog,
        )

        legacy = User.objects.create_user(
            username="close-legacy-fm",
            email="close-legacy-fm@test.az",
            password="x",
            role="property_fm",
            is_staff=True,
        )
        for code in SUPPLY_MUTATIONS_NOT_ON_ROLE:
            perm, _ = PermissionCode.objects.get_or_create(
                code=code, defaults={"name": code, "module": code.split(".", 1)[0]}
            )
            RolePermission.objects.get_or_create(role=Role.SERVICE_DESK, permission=perm)
            RolePermission.objects.get_or_create(role="property_fm", permission=perm)

        orphan = User.objects.create_user(
            username="close-exception",
            email="close-exception@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(orphan, "warehouse.edit")

        result = reconcile_retired_property_fm_role()
        self.assertGreaterEqual(result["users_remapped"], 1)
        legacy.refresh_from_db()
        self.assertEqual(legacy.role, Role.SERVICE_DESK)
        self.assertFalse(RolePermission.objects.filter(role="property_fm").exists())
        self.assertFalse(
            RolePermission.objects.filter(
                role=Role.SERVICE_DESK,
                permission__code__in=SUPPLY_MUTATIONS_NOT_ON_ROLE,
            ).exists()
        )
        self.assertTrue(
            UserPermission.objects.filter(
                user=orphan, permission__code="warehouse.edit"
            ).exists()
        )
        seed_rbac_catalog()
        seed_rbac_catalog()
        self.assertFalse(
            RolePermission.objects.filter(
                role=Role.SERVICE_DESK,
                permission__code__in=SUPPLY_MUTATIONS_NOT_ON_ROLE,
            ).exists()
        )
        self.assertFalse(user_has_permission(self.legacy_fm, "warehouse.edit"))
        self.assertFalse(user_has_permission(self.legacy_fm, "procurement.edit"))
        self.assertTrue(user_has_permission(orphan, "warehouse.edit"))
        self.assertTrue(user_has_permission(self.head, "procurement.edit"))
        self.assertTrue(user_has_permission(self.head, "warehouse.edit"))
