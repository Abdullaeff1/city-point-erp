"""Təkrar alış: əvvəlki PO əsasında yeni müstəqil PR (+ commitment → PO)."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus
from apps.procurement.models import POStatus, PurchaseOrder, PurchaseRequest
from apps.procurement.services import ProcurementService
from apps.procurement.tests.support import (
    approve_pending_commitment,
    approve_pr_via_management,
    issue_priced_po,
)
from apps.rbac.services import grant_user_permission, seed_rbac_catalog
from apps.warehouse.models import SKU, Stock, Warehouse
from apps.workflows.models import ApprovalRequest, ApprovalStatus

User = get_user_model()


@override_settings(PROCUREMENT_QUOTE_VAT_RATE="0.18")
class POReorderAcceptanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        cls.head = User.objects.create_user(
            username="reorder-head",
            email="reorder-head@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(cls.head, "supply.head")
        cls.other_head = User.objects.create_user(
            username="reorder-head-2",
            email="reorder-head-2@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(cls.other_head, "supply.head")
        cls.staff_sd = User.objects.create_user(
            username="reorder-sd",
            email="reorder-sd@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.viewer = User.objects.create_user(
            username="reorder-view",
            email="reorder-view@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.mgmt = User.objects.create_user(
            username="reorder-mgmt",
            email="reorder-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        cls.admin = User.objects.create_user(
            username="reorder-admin",
            email="reorder-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.wh = Warehouse.objects.create(code="REO-WH", name="Reorder WH")
        cls.sku_paper = SKU.objects.create(code="PAPER-40", name="Kağız paket", unit="paket")
        cls.sku_det = SKU.objects.create(code="DET-12", name="Yuyucu vasitə", unit="litr")
        Stock.objects.create(warehouse=cls.wh, sku=cls.sku_paper, quantity=Decimal("100"))
        Stock.objects.create(warehouse=cls.wh, sku=cls.sku_det, quantity=Decimal("50"))
        cls.sup = Party.objects.create(legal_name="Reorder Supplier LLC", status=PartyStatus.ACTIVE)
        PartyRole.objects.get_or_create(party=cls.sup, role=PartyRoleCode.SUPPLIER)
        cls.sup_b = Party.objects.create(legal_name="Other Split Sup", status=PartyStatus.ACTIVE)
        PartyRole.objects.get_or_create(party=cls.sup_b, role=PartyRoleCode.SUPPLIER)

    def _fully_received_source_po(self, *, actor=None) -> PurchaseOrder:
        actor = actor or self.head
        pr = ProcurementService.create_manual_pr(
            actor=actor,
            title="Köhnə rutin alış",
            lines=[
                {
                    "sku_id": self.sku_paper.pk,
                    "description": "Kağız paket",
                    "qty": "40",
                    "unit": "paket",
                },
                {
                    "sku_id": self.sku_det.pk,
                    "description": "Yuyucu vasitə",
                    "qty": "12",
                    "unit": "litr",
                },
            ],
        )
        # MANUAL PR escalation requires Admin (desk alone may only escalate WO/LOW_STOCK).
        approve_pr_via_management(pr, actor=self.admin, mgmt=self.mgmt)
        po = issue_priced_po(
            pr,
            supplier=self.sup,
            unit_price=Decimal("2.50"),
            actor=actor,
            mgmt=self.mgmt,
        )
        ProcurementService.receive_po(
            po,
            warehouse=self.wh,
            actor=actor,
            receive_mode="full",
            operation_key=f"recv-{po.code}",
        )
        po.refresh_from_db()
        self.assertEqual(po.status, POStatus.RECEIVED)
        return po

    def test_received_po_reorder_qty_edit_preserves_source(self):
        source = self._fully_received_source_po()
        old_pr = source.pr
        old_free = {
            ln.pk: ProcurementService.pr_line_free_to_allocate_qty(ln)
            for ln in old_pr.lines.all()
        }
        client = Client()
        client.force_login(self.head)
        url = reverse("erp:procurement_po_reorder", kwargs={"code": source.code})
        get = client.get(url)
        self.assertEqual(get.status_code, 200)
        self.assertContains(get, source.code)
        self.assertContains(get, "Bu sifariş əsasında yenisini yarat")
        before_pr = PurchaseRequest.objects.count()
        before_po = PurchaseOrder.objects.count()

        # Open-only / cancel does not create
        self.assertEqual(PurchaseRequest.objects.count(), before_pr)

        token = get.context["submit_token"]
        rows = list(get.context["rows"])
        self.assertEqual(len(rows), 2)
        post = {
            "submit_token": token,
            "title": "Təkrar — kağız və yuyucu",
            "notes": "",
            "line_0_source_po_line_id": rows[0]["source_po_line_id"],
            "line_0_sku_id": self.sku_paper.pk,
            "line_0_description": "Kağız paket",
            "line_0_qty": "40",
            "line_0_unit": "paket",
            "line_0_unit_price": "2.50",
            "line_1_source_po_line_id": rows[1]["source_po_line_id"],
            "line_1_sku_id": self.sku_det.pk,
            "line_1_description": "Yuyucu vasitə",
            "line_1_qty": "18",  # 12 → 18
            "line_1_unit": "litr",
            "line_1_unit_price": "2.50",
        }
        resp = client.post(url, post)
        self.assertEqual(resp.status_code, 302)
        new_pr = PurchaseRequest.objects.exclude(pk=old_pr.pk).latest("id")
        self.assertEqual(new_pr.source_po_id, source.pk)
        qtys = {ln.description: ln.qty for ln in new_pr.lines.all()}
        self.assertEqual(qtys["Kağız paket"], Decimal("40"))
        self.assertEqual(qtys["Yuyucu vasitə"], Decimal("18"))

        source.refresh_from_db()
        src_qtys = {ln.description: ln.qty for ln in source.lines.all()}
        self.assertEqual(src_qtys["Kağız paket"], Decimal("40"))
        self.assertEqual(src_qtys["Yuyucu vasitə"], Decimal("12"))

        old_pr.refresh_from_db()
        for ln in old_pr.lines.all():
            self.assertEqual(
                ProcurementService.pr_line_free_to_allocate_qty(ln), old_free[ln.pk]
            )

        # Double submit same token → one PR
        resp2 = client.post(url, post)
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(PurchaseRequest.objects.filter(source_po=source).count(), 1)

        # Intentional second reorder with new token
        get2 = client.get(url)
        token2 = get2.context["submit_token"]
        post["submit_token"] = token2
        post["line_1_qty"] = "20"
        resp3 = client.post(url, post)
        self.assertEqual(resp3.status_code, 302)
        self.assertEqual(PurchaseRequest.objects.filter(source_po=source).count(), 2)
        self.assertEqual(PurchaseOrder.objects.count(), before_po)  # still only source PO

    def test_form_get_and_cancel_create_nothing(self):
        source = self._fully_received_source_po()
        client = Client()
        client.force_login(self.head)
        url = reverse("erp:procurement_po_reorder", kwargs={"code": source.code})
        n_pr = PurchaseRequest.objects.count()
        n_po = PurchaseOrder.objects.count()
        n_appr = ApprovalRequest.objects.count()
        self.assertEqual(client.get(url).status_code, 200)
        # "cancel" = GET detail again without POST
        self.assertEqual(
            client.get(reverse("erp:procurement_po_detail", kwargs={"code": source.code})).status_code,
            200,
        )
        self.assertEqual(PurchaseRequest.objects.count(), n_pr)
        self.assertEqual(PurchaseOrder.objects.count(), n_po)
        self.assertEqual(ApprovalRequest.objects.count(), n_appr)

    def test_old_commitment_cannot_issue_new_priced_po_needs_fresh_approval(self):
        source = self._fully_received_source_po()
        stock_before = {
            s.sku_id: s.quantity
            for s in Stock.objects.filter(warehouse=self.wh)
        }
        new_pr = ProcurementService.reorder_from_po(
            source,
            actor=self.head,
            lines=[
                {
                    "sku_id": self.sku_paper.pk,
                    "description": "Kağız paket",
                    "qty": "40",
                    "unit": "paket",
                    "unit_price": "2.50",
                },
                {
                    "sku_id": self.sku_det.pk,
                    "description": "Yuyucu vasitə",
                    "qty": "18",
                    "unit": "litr",
                    "unit_price": "2.50",
                },
            ],
        )
        approve_pr_via_management(new_pr, actor=self.admin, mgmt=self.mgmt)

        # Köhnə PR öhdəliyi bu yeni PR üçün uyğun gəlmir — qiymətli buraxılış bloklanır
        po_before = PurchaseOrder.objects.count()
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                new_pr,
                supplier_party=self.sup,
                actor=self.head,
                line_unit_prices=ProcurementService.reorder_line_unit_prices(new_pr),
            )
        self.assertEqual(PurchaseOrder.objects.count(), po_before)

        # Yeni Management öhdəlik təsdiqindən sonra bir SENT PO
        approve_pending_commitment(new_pr, mgmt=self.mgmt)
        new_po = ProcurementService.create_po_from_pr(
            new_pr,
            supplier_party=self.sup,
            actor=self.head,
            line_unit_prices=ProcurementService.reorder_line_unit_prices(new_pr),
        )
        self.assertEqual(new_po.status, POStatus.SENT)
        self.assertEqual(new_po.source_po_id, source.pk)
        qtys = {ln.description: ln.qty for ln in new_po.lines.all()}
        self.assertEqual(qtys["Kağız paket"], Decimal("40"))
        self.assertEqual(qtys["Yuyucu vasitə"], Decimal("18"))
        for s in Stock.objects.filter(warehouse=self.wh):
            self.assertEqual(s.quantity, stock_before[s.sku_id])

    def test_split_order_only_selected_po_lines(self):
        # İki ayrı PO — təkrar alış yalnız seçilmiş PO sətirlərini götürür
        from apps.audit.services import log_action
        from apps.procurement.models import POLine

        po_a = PurchaseOrder.objects.create(
            code="PO-SPLIT-A",
            supplier_party=self.sup,
            status=POStatus.RECEIVED,
        )
        POLine.objects.create(
            po=po_a,
            description="Kağız paket",
            sku=self.sku_paper,
            qty=Decimal("10"),
            unit_price=Decimal("1.00"),
        )
        log_action(
            action="procurement.po.create",
            actor=self.head,
            entity=po_a,
            new_values={"code": po_a.code},
        )
        po_b = PurchaseOrder.objects.create(
            code="PO-SPLIT-B",
            supplier_party=self.sup_b,
            status=POStatus.RECEIVED,
        )
        POLine.objects.create(
            po=po_b,
            description="Yuyucu vasitə",
            sku=self.sku_det,
            qty=Decimal("5"),
            unit_price=Decimal("3.00"),
        )
        log_action(
            action="procurement.po.create",
            actor=self.head,
            entity=po_b,
            new_values={"code": po_b.code},
        )
        rows = ProcurementService.reorder_form_rows(po_a)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["description"], "Kağız paket")
        self.assertNotIn("Yuyucu", rows[0]["description"])
        new_pr = ProcurementService.reorder_from_po(
            po_a,
            actor=self.head,
            lines=[
                {
                    "sku_id": self.sku_paper.pk,
                    "description": "Kağız paket",
                    "qty": "10",
                    "unit": "paket",
                    "unit_price": "1.00",
                }
            ],
        )
        self.assertEqual(new_pr.lines.count(), 1)
        self.assertEqual(new_pr.lines.get().description, "Kağız paket")
        self.assertEqual(po_b.lines.count(), 1)

    def test_unauthorized_roles_and_foreign_po_fail(self):
        source = self._fully_received_source_po(actor=self.head)
        client = Client()
        url = reverse("erp:procurement_po_reorder", kwargs={"code": source.code})
        detail = reverse("erp:procurement_po_detail", kwargs={"code": source.code})

        # Ordinary SD — no button, POST denied
        client.force_login(self.staff_sd)
        self.assertNotContains(client.get(detail), "Bu sifariş əsasında yenisini yarat")
        self.assertIn(client.get(url).status_code, (302, 403))
        n_pr = PurchaseRequest.objects.count()
        post = {
            "submit_token": "x",
            "title": "hack",
            "line_0_description": "Kağız paket",
            "line_0_qty": "1",
            "line_0_unit": "paket",
            "line_0_sku_id": self.sku_paper.pk,
            "line_0_unit_price": "1",
        }
        self.assertIn(client.post(url, post).status_code, (302, 403))
        self.assertEqual(PurchaseRequest.objects.count(), n_pr)

        # Other supply.head — ownership fails
        client.force_login(self.other_head)
        self.assertIn(client.get(url).status_code, (302, 403))
        with self.assertRaises(DomainError):
            ProcurementService.reorder_from_po(
                source,
                actor=self.other_head,
                lines=[
                    {
                        "sku_id": self.sku_paper.pk,
                        "description": "Kağız paket",
                        "qty": "1",
                        "unit": "paket",
                        "unit_price": "1",
                    }
                ],
            )
        self.assertEqual(PurchaseRequest.objects.count(), n_pr)

        # Detail shows button for owner; new PR shows source link
        client.force_login(self.head)
        self.assertContains(client.get(detail), "Bu sifariş əsasında yenisini yarat")
        pr = ProcurementService.reorder_from_po(
            source,
            actor=self.head,
            lines=[
                {
                    "sku_id": self.sku_paper.pk,
                    "description": "Kağız paket",
                    "qty": "1",
                    "unit": "paket",
                    "unit_price": "1",
                }
            ],
        )
        pr_page = client.get(reverse("erp:procurement_pr_detail", kwargs={"code": pr.code}))
        self.assertContains(pr_page, "Əvvəlki sifariş")
        self.assertContains(pr_page, source.code)
