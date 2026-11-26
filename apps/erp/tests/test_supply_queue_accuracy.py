"""Supply ready/pending queue accuracy — issuable commitments, not draft+supplier."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.erp.department_dashboards import build_supply_dashboard
from apps.parties.models import Party, PartyRole, PartyRoleCode
from apps.procurement.models import POStatus, PurchaseOrder, PurchaseRequest
from apps.procurement.services import (
    WF_PROCUREMENT_COMMITMENT,
    WF_PROCUREMENT_PR,
    ProcurementService,
)
from apps.procurement.tests.support import (
    approve_pending_commitment,
    approve_pr_via_management,
    issue_priced_po,
)
from apps.rbac.services import grant_user_permission, seed_rbac_catalog, user_has_permission
from apps.warehouse.models import SKU, Warehouse
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

User = get_user_model()


class SupplyReadyQueueAccuracyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.head = User.objects.create_user(
            username="q-head",
            email="q-head@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(cls.head, "supply.head")
        cls.desk = User.objects.create_user(
            username="q-desk",
            email="q-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.mgmt = User.objects.create_user(
            username="q-mgmt",
            email="q-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        cls.admin = User.objects.create_user(
            username="q-admin",
            email="q-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.wh = Warehouse.objects.create(code="QWH", name="Q WH")
        cls.sku = SKU.objects.create(code="Q-SKU", name="Bolt", unit="pcs", reorder_level=1)
        cls.sup_a = Party.objects.create(legal_name="Queue Supplier A")
        cls.sup_b = Party.objects.create(legal_name="Queue Supplier B")
        PartyRole.objects.get_or_create(party=cls.sup_a, role=PartyRoleCode.SUPPLIER)
        PartyRole.objects.get_or_create(party=cls.sup_b, role=PartyRoleCode.SUPPLIER)

    def _pr(self, title="Q PR"):
        # Manual PR escalation requires Admin (or WO/LOW_STOCK for Supply).
        return ProcurementService.create_manual_pr(
            actor=self.admin,
            title=title,
            lines=[{"sku_id": self.sku.pk, "description": "Bolt", "qty": "10", "unit": "pcs"}],
        )

    def _ready_queue(self, user):
        board = build_supply_dashboard(user)
        return next(q for q in board["queues"] if "hazır" in q["label"])

    def _pending_queue(self, user):
        board = build_supply_dashboard(user)
        return next(q for q in board["queues"] if "Rəhbər" in q["label"])

    def test_draft_supplier_without_priced_approval_not_ready(self):
        pr = self._pr("draft only")
        approve_pr_via_management(pr, actor=self.admin, mgmt=self.mgmt)
        po = ProcurementService.create_po_from_pr(
            pr, supplier_party=self.sup_a, actor=self.head, line_qtys={pr.lines.get().pk: "10"}
        )
        self.assertEqual(po.status, POStatus.DRAFT)
        ready = self._ready_queue(self.head)
        self.assertEqual(ready["count"], 0)
        self.assertEqual(ProcurementService.list_issuable_commitments(), [])

    def test_process_only_pr_approval_not_ready(self):
        pr = self._pr("process only")
        approve_pr_via_management(pr, actor=self.admin, mgmt=self.mgmt)
        ready = self._ready_queue(self.head)
        self.assertEqual(ready["count"], 0)

    def test_pending_commitment_not_ready_but_in_pending(self):
        pr = self._pr("pending commit")
        approve_pr_via_management(pr, actor=self.admin, mgmt=self.mgmt)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr, supplier_party=self.sup_a, actor=self.head, unit_price="5"
            )
        pending_rows = ProcurementService.list_pending_procurement_approvals(kind="commitment")
        self.assertEqual(len(pending_rows), 1)
        pending_id = pending_rows[0].pk
        ready = self._ready_queue(self.head)
        self.assertEqual(ready["count"], 0)
        pend = self._pending_queue(self.head)
        self.assertGreaterEqual(pend["count"], 1)
        c = Client()
        c.force_login(self.head)
        resp = c.get(pend["url"])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(user_has_permission(self.head, "approval.decide"))
        self.assertIn(pending_id, [r.pk for r in resp.context["pending"]])
        self.assertEqual(resp.context["pending_total"], len(resp.context["pending"]))
        self.assertFalse(resp.context["can_decide"])

    def test_approved_unused_matching_commitment_is_ready_exact_ids(self):
        pr = self._pr("ready A")
        approve_pr_via_management(pr, actor=self.admin, mgmt=self.mgmt)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr, supplier_party=self.sup_a, actor=self.head, unit_price="5"
            )
        commitment = approve_pending_commitment(pr, mgmt=self.mgmt)
        ready_rows = ProcurementService.list_issuable_commitments()
        self.assertEqual([r.pk for r in ready_rows], [commitment.pk])
        card = self._ready_queue(self.head)
        self.assertEqual(card["count"], 1)
        self.assertEqual(str(card["unit"]), "təsdiqlənmiş öhdəlik")
        c = Client()
        c.force_login(self.head)
        resp = c.get(card["url"])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["ready_total"], 1)
        self.assertEqual(resp.context["ready_ids"], [commitment.pk])
        self.assertContains(resp, f'data-approval-id="{commitment.pk}"')

    def test_changed_terms_after_approval_excluded(self):
        pr = self._pr("stale terms")
        approve_pr_via_management(pr, actor=self.admin, mgmt=self.mgmt)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr, supplier_party=self.sup_a, actor=self.head, unit_price="5"
            )
        commitment = approve_pending_commitment(pr, mgmt=self.mgmt)
        # Mutate PR qty → fingerprint no longer matches
        line = pr.lines.get()
        line.qty = Decimal("12")
        line.save(update_fields=["qty"])
        self.assertFalse(
            ProcurementService.commitment_still_matches_current_terms(commitment)
        )
        self.assertEqual(ProcurementService.list_issuable_commitments(), [])
        self.assertEqual(self._ready_queue(self.head)["count"], 0)

    def test_consumed_approval_excluded(self):
        pr = self._pr("consumed")
        approve_pr_via_management(pr, actor=self.admin, mgmt=self.mgmt)
        po = issue_priced_po(pr, supplier=self.sup_a, unit_price="5", actor=self.head, mgmt=self.mgmt)
        self.assertEqual(po.status, POStatus.SENT)
        ct = ContentType.objects.get_for_model(PurchaseRequest)
        consumed = ApprovalRequest.objects.filter(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            status=ApprovalStatus.APPROVED,
            entity_type=ct,
            entity_id=pr.pk,
        ).get()
        self.assertTrue((consumed.payload or {}).get("consumed_po_id"))
        self.assertEqual(ProcurementService.list_issuable_commitments(), [])
        self.assertEqual(self._ready_queue(self.head)["count"], 0)

    def test_supplier_a_approved_b_pending_only_a_ready(self):
        pr = self._pr("split A/B")
        approve_pr_via_management(pr, actor=self.admin, mgmt=self.mgmt)
        line_id = pr.lines.get().pk
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr,
                supplier_party=self.sup_a,
                actor=self.head,
                unit_price="5",
                line_qtys={line_id: "6"},
            )
        commit_a = approve_pending_commitment(pr, mgmt=self.mgmt)
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr,
                supplier_party=self.sup_b,
                actor=self.head,
                unit_price="7",
                line_qtys={line_id: "4"},
            )
        pending_b = ApprovalRequest.objects.get(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            status=ApprovalStatus.PENDING,
            entity_id=pr.pk,
        )
        ready_ids = [r.pk for r in ProcurementService.list_issuable_commitments()]
        self.assertEqual(ready_ids, [commit_a.pk])
        self.assertNotIn(pending_b.pk, ready_ids)
        card = self._ready_queue(self.head)
        self.assertEqual(card["count"], 1)
        c = Client()
        c.force_login(self.head)
        resp = c.get(card["url"])
        self.assertEqual(resp.context["ready_ids"], [commit_a.pk])
        self.assertEqual(resp.context["ready_total"], 1)

    def test_empty_pending_queue_and_direct_url(self):
        self.assertEqual(
            ProcurementService.list_pending_procurement_approvals(kind="all"), []
        )
        c = Client()
        c.force_login(self.head)
        resp = c.get(reverse("erp:procurement_pending_approvals"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["pending_total"], 0)
        # Ordinary desk with procurement.view can open RO list; decide stays false
        c2 = Client()
        c2.force_login(self.desk)
        resp2 = c2.get(reverse("erp:procurement_pending_approvals"))
        self.assertEqual(resp2.status_code, 200)
        self.assertFalse(resp2.context["can_decide"])
        # Management decide hub remains separate
        c3 = Client()
        c3.force_login(self.mgmt)
        hub = c3.get(reverse("erp:approvals") + "?workflow=procurement")
        self.assertEqual(hub.status_code, 200)
        self.assertTrue(hub.context["can_decide"])
