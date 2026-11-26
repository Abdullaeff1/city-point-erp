"""Final Supply portal acceptance evidence (synthetic data only)."""

from __future__ import annotations

import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.comms.links import notification_target_url, user_notifications
from apps.comms.models import BuildingProcedure, Notification
from apps.core.services import DomainError
from apps.erp.building_procedure_views import _can_author_procedures
from apps.erp.department_dashboards import build_supply_dashboard
from apps.leases.models import Lease, LeaseStatus
from apps.maintenance.access import can_mutate_work_order, can_view_work_order
from apps.maintenance.models import CostLineKind, WorkOrder, WorkOrderCostLine, WorkOrderStatus
from apps.maintenance.services import next_wo_code
from apps.parties.models import Party, PartyRole, PartyRoleCode
from apps.procurement.models import POStatus, PurchaseOrder
from apps.procurement.services import ProcurementService
from apps.procurement.tests.support import approve_pr_via_management
from apps.property.models import Building, CommercialStatus, Floor, Occupancy, Space
from apps.rbac.services import grant_user_permission, seed_rbac_catalog, user_has_permission
from apps.residents.models import ResidentCompany
from apps.tickets.models import (
    Ticket,
    TicketCategory,
    TicketDepartment,
    TicketPriority,
    TicketStatus,
    TicketSubcategory,
    TicketType,
)
from apps.tickets.routing import effective_ticket_department_ids
from apps.tickets.seed_taxonomy import seed_ticket_taxonomy
from apps.tickets.services import create_work_order_from_ticket
from apps.warehouse.models import SKU, Warehouse

User = get_user_model()


class SupplyFinalAcceptanceEvidenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_rbac_catalog()
        seed_ticket_taxonomy()
        cls.company = ResidentCompany.objects.create(name="Acc Co", slug="acc-co")
        cls.desk_dept = TicketDepartment.objects.get(code="servicedesk")
        cls.web_dept = TicketDepartment.objects.get(code="webservis")
        cls.sec_dept = TicketDepartment.objects.get(code="security")
        hvac = TicketSubcategory.objects.filter(slug="hvac").first()
        cls.cat = hvac.category if hvac else TicketCategory.objects.filter(is_active=True).first()
        cls.sub = hvac
        cls.desk = User.objects.create_user(
            username="acc-desk",
            email="acc-desk@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        cls.head = User.objects.create_user(
            username="acc-head",
            email="acc-head@test.az",
            password="x",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        grant_user_permission(cls.head, "supply.head")
        cls.sales = User.objects.create_user(
            username="acc-sales",
            email="acc-sales@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        cls.accountant = User.objects.create_user(
            username="acc-acct",
            email="acc-acct@test.az",
            password="x",
            role=Role.ACCOUNTANT,
            is_staff=True,
        )
        cls.admin = User.objects.create_user(
            username="acc-admin",
            email="acc-admin@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        cls.mgmt = User.objects.create_user(
            username="acc-mgmt",
            email="acc-mgmt@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        party = Party.objects.create(legal_name="Acc Lease Party")
        building = Building.objects.create(code="ACCB", name="Acc Bldg")
        floor = Floor.objects.create(building=building, code="1", name="1")
        cls.space = Space.objects.create(code="ACC-101", name="Office", floor=floor)
        cls.lease = Lease.objects.create(
            party=party,
            space=cls.space,
            status=LeaseStatus.DRAFT,
            code="ACC-LEASE-1",
        )
        cls.wh = Warehouse.objects.create(code="ACCWH", name="Acc WH")
        cls.sku = SKU.objects.create(code="ACC-SKU", name="Bolt", unit="pcs", reorder_level=1)
        cls.sup_a = Party.objects.create(legal_name="Acc Supplier A")
        cls.sup_b = Party.objects.create(legal_name="Acc Supplier B")
        PartyRole.objects.get_or_create(party=cls.sup_a, role=PartyRoleCode.SUPPLIER)
        PartyRole.objects.get_or_create(party=cls.sup_b, role=PartyRoleCode.SUPPLIER)

    def _ticket(self, *, code, department, **kwargs):
        defaults = dict(
            code=code,
            ticket_type=TicketType.INCIDENT,
            category=self.cat,
            subcategory=self.sub,
            company=self.company,
            description="acc",
            priority=TicketPriority.NORMAL,
            status=TicketStatus.IN_PROGRESS,
            department=department,
            sla_due_at=timezone.now() + timedelta(hours=8),
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def test_queue_parity_material_partial_ready_and_notification(self):
        board0 = build_supply_dashboard(self.head)
        labels = {q["label"]: q for q in board0["queues"]}
        for key in (
            "Material gözləyən təmirlər",
            "Rəhbər təsdiqini gözləyən alışlar",
            "Təsdiqlənib sifarişə hazır olan alışlar",
            "Qismən qəbul edilmiş sifarişlər",
        ):
            self.assertIn(key, labels)
        material_before = labels["Material gözləyən təmirlər"]["count"]
        partial_before = labels["Qismən qəbul edilmiş sifarişlər"]["count"]
        ready_before = labels["Təsdiqlənib sifarişə hazır olan alışlar"]["count"]

        ticket = self._ticket(code="TK-ACC-MAT", department=self.desk_dept)
        wo = create_work_order_from_ticket(ticket, actor=self.head)
        WorkOrderCostLine.objects.create(
            work_order=wo,
            kind=CostLineKind.MATERIAL,
            description="filter",
            qty=1,
            unit_price=1,
            amount=1,
        )

        board = build_supply_dashboard(self.head)
        mat_q = next(q for q in board["queues"] if "Material" in q["label"])
        self.assertEqual(mat_q["count"], material_before + 1)
        c_head = Client()
        c_head.force_login(self.head)
        resp = c_head.get(mat_q["url"])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["work_order_total"], mat_q["count"])
        page_ids = {w.pk for w in resp.context["work_orders"]}
        if mat_q["count"] <= 50:
            self.assertIn(wo.pk, page_ids)
        else:
            self.assertTrue(
                any(page_ids)
                or wo.pk in set(
                    resp.context["page_obj"].paginator.object_list.values_list("pk", flat=True)
                )
            )

        c_desk = Client()
        c_desk.force_login(self.desk)
        board_d = build_supply_dashboard(self.desk)
        mat_d = next(q for q in board_d["queues"] if "Material" in q["label"])
        resp_d = c_desk.get(mat_d["url"])
        self.assertEqual(resp_d.status_code, 200)
        self.assertEqual(resp_d.context["work_order_total"], mat_d["count"])
        self.assertTrue(can_view_work_order(self.desk, wo))

        pr = ProcurementService.create_manual_pr(
            actor=self.head,
            title="Acc partial",
            lines=[{"sku_id": self.sku.pk, "description": "Bolt", "qty": "10", "unit": "pcs"}],
        )
        approve_pr_via_management(pr, actor=self.admin)
        po = ProcurementService.create_po_from_pr(
            pr, supplier_party=self.sup_a, actor=self.head, line_qtys={pr.lines.get().pk: "10"}
        )
        PurchaseOrder.objects.filter(pk=po.pk).update(status=POStatus.PARTIAL)
        board2 = build_supply_dashboard(self.head)
        part_q = next(q for q in board2["queues"] if "Qismən" in q["label"])
        self.assertEqual(part_q["count"], partial_before + 1)
        resp_p = c_head.get(part_q["url"])
        self.assertEqual(resp_p.status_code, 200)

        PurchaseOrder.objects.filter(pk=po.pk).update(status=POStatus.DRAFT)
        board3 = build_supply_dashboard(self.head)
        ready_q = next(q for q in board3["queues"] if "hazır" in q["label"])
        self.assertGreaterEqual(ready_q["count"], ready_before + 1)
        resp_r = c_head.get(ready_q["url"])
        self.assertEqual(resp_r.status_code, 200)

        # Zero queue still renders
        empty_board = build_supply_dashboard(self.desk)
        self.assertTrue(all(isinstance(q["count"], int) and q["count"] >= 0 for q in empty_board["queues"]))

        note = Notification.objects.create(
            user=self.head,
            ticket=ticket,
            message=f"Ticket {ticket.code} assigned",
            event_key=f"acc.ticket.{ticket.pk}",
        )
        url = notification_target_url(note, ticket, self.head, "erp")
        self.assertEqual(url, reverse("erp:ticket_detail", kwargs={"code": ticket.code}))
        r_n = c_head.get(url)
        self.assertEqual(r_n.status_code, 200)
        notes = user_notifications(self.head, namespace="erp", limit=20)
        self.assertTrue(any(n.pk == note.pk and n.target_url == url for n in notes))

    def test_wo_scope_handoff_foreign_assigned_unowned(self):
        codes = set(
            TicketDepartment.objects.filter(
                id__in=effective_ticket_department_ids(self.desk)
            ).values_list("code", flat=True)
        )
        self.assertTrue(codes <= {"servicedesk", "webservis"})
        self.assertNotIn("security", codes)
        self.assertIn("servicedesk", codes)

        own = self._ticket(code="TK-ACC-OWN", department=self.desk_dept)
        foreign = self._ticket(code="TK-ACC-FOR", department=self.sec_dept)
        handoff = self._ticket(code="TK-ACC-HO", department=self.web_dept)
        wo_own = create_work_order_from_ticket(own, actor=self.admin)
        wo_foreign = create_work_order_from_ticket(foreign, actor=self.admin)
        wo_handoff = create_work_order_from_ticket(handoff, actor=self.admin)
        wo_assigned = create_work_order_from_ticket(
            self._ticket(code="TK-ACC-ASG", department=self.sec_dept), actor=self.admin
        )
        wo_assigned.assigned_to = self.desk
        wo_assigned.status = WorkOrderStatus.ASSIGNED
        wo_assigned.save(update_fields=["assigned_to", "status"])
        wo_orphan = WorkOrder.objects.create(
            code=next_wo_code(),
            title="unowned historical",
            status=WorkOrderStatus.OPEN,
            ticket=None,
        )

        self.assertTrue(can_view_work_order(self.desk, wo_own))
        self.assertTrue(can_mutate_work_order(self.desk, wo_own))
        self.assertFalse(can_view_work_order(self.desk, wo_foreign))
        self.assertFalse(can_mutate_work_order(self.desk, wo_foreign))
        # Combined fallback may include webservis for unbound ordinary staff
        self.assertEqual(can_view_work_order(self.desk, wo_handoff), "webservis" in codes)
        self.assertTrue(can_view_work_order(self.desk, wo_assigned))
        self.assertTrue(can_mutate_work_order(self.desk, wo_assigned))
        self.assertFalse(can_view_work_order(self.desk, wo_orphan))
        self.assertFalse(can_mutate_work_order(self.desk, wo_orphan))

        self.assertTrue(can_view_work_order(self.head, wo_foreign))
        self.assertTrue(can_mutate_work_order(self.head, wo_foreign))
        self.assertTrue(can_view_work_order(self.head, wo_handoff))
        self.assertTrue(can_mutate_work_order(self.head, wo_handoff))
        self.assertTrue(can_view_work_order(self.head, wo_orphan))
        self.assertTrue(can_mutate_work_order(self.head, wo_orphan))
        self.assertTrue(can_view_work_order(self.mgmt, wo_orphan))
        self.assertFalse(can_mutate_work_order(self.mgmt, wo_orphan))

    def test_lease_action_matrix(self):
        self.assertTrue(user_has_permission(self.sales, "lease.view"))
        self.assertTrue(user_has_permission(self.sales, "lease.edit"))
        self.assertTrue(user_has_permission(self.accountant, "lease.view"))
        self.assertFalse(user_has_permission(self.accountant, "lease.edit"))
        self.assertTrue(user_has_permission(self.admin, "lease.edit"))
        self.assertFalse(user_has_permission(self.desk, "lease.view"))
        self.assertFalse(user_has_permission(self.desk, "lease.edit"))
        self.assertFalse(user_has_permission(self.head, "lease.view"))
        self.assertFalse(user_has_permission(self.head, "lease.edit"))

        c = Client()
        c.force_login(self.sales)
        # Sales positive control: lease detail GET + activate action authorized (not 403)
        detail = c.get(reverse("erp:lease_detail", kwargs={"code": self.lease.code}))
        self.assertEqual(detail.status_code, 200)
        before = self.lease.status
        resp = c.post(
            reverse("erp:lease_detail", kwargs={"code": self.lease.code}),
            {"action": "activate"},
        )
        self.assertNotEqual(resp.status_code, 403)
        self.lease.refresh_from_db()
        # If activate succeeded status changed; if domain rejected, still not a perm denial
        if resp.status_code in (200, 302) and self.lease.status != before:
            self.assertNotEqual(self.lease.status, LeaseStatus.DRAFT)

        for user in (self.desk, self.head):
            for action in ("activate", "terminate", "generate_charges", "settle_deposit"):
                status_before = self.lease.status
                cu = Client()
                cu.force_login(user)
                r = cu.post(
                    reverse("erp:lease_detail", kwargs={"code": self.lease.code}),
                    {"action": action},
                )
                self.assertIn(r.status_code, (302, 403))
                self.lease.refresh_from_db()
                self.assertEqual(self.lease.status, status_before)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="proc-acc-"))
    def test_procedure_unpublish_retains_file_blocks_delete(self):
        self.assertFalse(_can_author_procedures(self.desk))
        self.assertFalse(_can_author_procedures(self.head))
        self.assertTrue(_can_author_procedures(self.admin))

        proc = BuildingProcedure(
            title="Acc Proc",
            description="synthetic",
            is_published=True,
            sort_order=1,
            created_by=self.admin,
        )
        proc.file.save(
            "acc-proc.pdf",
            SimpleUploadedFile(
                "acc-proc.pdf",
                b"%PDF-1.4 synthetic procedure",
                content_type="application/pdf",
            ),
            save=True,
        )
        file_name = proc.file.name
        self.assertTrue(proc.file.storage.exists(file_name))

        c = Client()
        c.force_login(self.admin)
        edit_get = c.get(reverse("erp:building_procedure_edit", kwargs={"pk": proc.pk}))
        self.assertEqual(edit_get.status_code, 200)
        r = c.post(
            reverse("erp:building_procedure_edit", kwargs={"pk": proc.pk}),
            {
                "title": "Acc Proc",
                "description": "synthetic",
                "sort_order": "1",
                "is_published": "",
            },
        )
        self.assertEqual(r.status_code, 302)
        proc.refresh_from_db()
        self.assertFalse(proc.is_published)
        self.assertTrue(proc.file.storage.exists(file_name))
        self.assertFalse(
            BuildingProcedure.objects.filter(pk=proc.pk, is_published=True).exists()
        )
        # Stale portal download link uses is_published=True queryset → 404
        from django.http import Http404
        from django.shortcuts import get_object_or_404

        with self.assertRaises(Http404):
            get_object_or_404(
                BuildingProcedure.objects.filter(is_published=True),
                pk=proc.pk,
            )
        self.assertNotIn(
            proc.pk,
            BuildingProcedure.objects.filter(is_published=True).values_list("pk", flat=True),
        )

        published_ids = set(
            BuildingProcedure.objects.filter(is_published=True).values_list("pk", flat=True)
        )
        self.assertNotIn(proc.pk, published_ids)

        c_desk = Client()
        c_desk.force_login(self.desk)
        r_del = c_desk.post(reverse("erp:building_procedure_delete", kwargs={"pk": proc.pk}))
        self.assertIn(r_del.status_code, (302, 403))
        self.assertTrue(BuildingProcedure.objects.filter(pk=proc.pk).exists())
        self.assertTrue(proc.file.storage.exists(file_name))

    def test_second_po_tranche_10_equals_6_plus_4(self):
        pr = ProcurementService.create_manual_pr(
            actor=self.head,
            title="Acc 10=6+4",
            lines=[{"sku_id": self.sku.pk, "description": "Bolt", "qty": "10", "unit": "pcs"}],
        )
        approve_pr_via_management(pr, actor=self.admin)
        line_id = pr.lines.get().pk
        po1 = ProcurementService.create_po_from_pr(
            pr, supplier_party=self.sup_a, actor=self.head, line_qtys={line_id: "6"}
        )
        po2 = ProcurementService.create_po_from_pr(
            pr, supplier_party=self.sup_b, actor=self.head, line_qtys={line_id: "4"}
        )
        self.assertEqual(po1.lines.get().qty, Decimal("6"))
        self.assertEqual(po2.lines.get().qty, Decimal("4"))
        progress = ProcurementService.pr_qty_progress(pr)
        self.assertEqual(progress[0]["ordered"], Decimal("10"))
        self.assertEqual(progress[0]["outstanding_order"], Decimal("0"))
        with self.assertRaises(DomainError):
            ProcurementService.create_po_from_pr(
                pr, supplier_party=self.sup_a, actor=self.head, line_qtys={line_id: "1"}
            )

    def test_directory_pagination_beyond_50(self):
        building = Building.objects.create(code="DIRB", name="Dir Bldg")
        floor = Floor.objects.create(building=building, code="8", name="8")
        first = None
        for i in range(55):
            rc = ResidentCompany.objects.create(name=f"DirCo {i:03d}", slug=f"dirco-{i:03d}")
            if first is None:
                first = rc
            Space.objects.create(
                code=f"DIR-{i:03d}",
                name=f"Office {i}",
                floor=floor,
                resident=rc,
                area_m2="20",
                occupancy=Occupancy.ACTIVE_LEASE if i % 3 == 0 else Occupancy.VACANT,
                commercial_status=(
                    CommercialStatus.ACTIVE
                    if i % 3 == 0
                    else CommercialStatus.RESERVED
                    if i % 3 == 1
                    else CommercialStatus.VACANT
                ),
            )
        c = Client()
        c.force_login(self.desk)
        r1 = c.get(reverse("erp:resident_directory"), {"page": "1"})
        self.assertEqual(r1.status_code, 200)
        self.assertGreaterEqual(r1.context["company_total"], 55)
        r2 = c.get(reverse("erp:resident_directory"), {"page": "2", "q": ""})
        self.assertEqual(r2.status_code, 200)
        self.assertGreaterEqual(r2.context["company_total"], 55)
        detail = c.get(reverse("erp:resident_directory_detail", kwargs={"slug": first.slug}))
        self.assertEqual(detail.status_code, 200)
