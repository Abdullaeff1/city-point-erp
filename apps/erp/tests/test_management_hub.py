"""Rəhbərlik ERP modul hub — tema, qərar növbəsi, AR/AP ayrımı, KPI keçidləri."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.mgmt_nav import build_management_nav
from apps.accounts.models import Role
from apps.erp.management_hub import build_management_hub
from apps.leases.models import Lease, LeaseStatus
from apps.maintenance.models import WorkOrder, WorkOrderStatus
from apps.parties.models import Party, PartyStatus, PartyType
from apps.property.models import Building, Floor, Space
from apps.rbac.services import seed_rbac_catalog

User = get_user_model()


class ManagementHubTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.manager = User.objects.create_user(
            username="mgr_hub",
            email="mgr_hub@test.az",
            password="x",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username="admin_hub",
            email="admin_hub@test.az",
            password="x",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.sales = User.objects.create_user(
            username="sales_hub",
            email="sales_hub@test.az",
            password="x",
            role=Role.SALES,
            is_staff=True,
        )
        self.client = Client()

    def test_management_dashboard_hub(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_management_hub"])
        self.assertFalse(resp.context.get("is_sales_dashboard"))
        self.assertContains(resp, "cp-theme-mgmt")
        self.assertContains(resp, "Rəhbərlik paneli")
        self.assertIn("decision_queue", resp.context)
        self.assertIn("building_kpis", resp.context)
        self.assertIn("kpi_portfolio", resp.context)
        self.assertContains(resp, "Qərar növbəsi")
        self.assertContains(resp, "queue=ar")
        self.assertContains(resp, "queue=ap")
        self.assertContains(resp, "Son bildirişlər")
        self.assertContains(resp, "Sahə üzrə doluluq")
        self.assertNotContains(resp, "GL yazma yalnız")
        # Workflow codes may remain in href filters; visible descriptions must not show them
        for row in resp.context["decision_queue"]:
            self.assertNotIn("crm.offer.send", str(row.get("meta") or ""))
            self.assertNotIn("finance.payment", str(row.get("meta") or ""))
            self.assertNotIn("crm.offer.send", str(row.get("action") or ""))
            self.assertNotIn("finance.payment", str(row.get("action") or ""))
        body = resp.content.decode("utf-8")
        self.assertNotIn('href="/security/"', body)
        self.assertNotIn('href="/finance/"', body)
        self.assertNotContains(resp, "İş sahələri")

    def test_ar_ap_queues_separate(self):
        self.client.force_login(self.manager)
        ar = self.client.get(reverse("erp:payment_approvals") + "?queue=ar")
        self.assertEqual(ar.status_code, 200)
        self.assertTrue(ar.context["show_ar"])
        self.assertFalse(ar.context["show_ap"])
        self.assertContains(ar, "Debitor (AR)")
        self.assertContains(ar, "Qeydə alınmış kiracı ödənişləri")
        self.assertNotContains(ar, "Qeydə alınmış podratçı ödənişləri")

        ap = self.client.get(reverse("erp:payment_approvals") + "?queue=ap")
        self.assertEqual(ap.status_code, 200)
        self.assertFalse(ap.context["show_ar"])
        self.assertTrue(ap.context["show_ap"])
        self.assertContains(ap, "Kreditor (AP)")
        self.assertContains(ap, "Qeydə alınmış podratçı ödənişləri")
        self.assertNotContains(ap, "Qeydə alınmış kiracı ödənişləri")

    def test_admin_keeps_ops_not_hub(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("erp:dashboard") + "?ops=1")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context.get("is_management_hub"))
        self.assertNotContains(resp, "cp-theme-mgmt")

    def test_sales_unchanged(self):
        self.client.force_login(self.sales)
        resp = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_sales_dashboard"])
        self.assertFalse(resp.context.get("is_management_hub"))
        self.assertContains(resp, "cp-theme-crm")
        self.assertNotContains(resp, "cp-theme-mgmt")

    def test_management_module_urls_ok(self):
        from apps.residents.models import ResidentCompany

        ResidentCompany.objects.create(
            name="City Point", slug="city-point", status="active", is_internal=True
        )
        tenant = ResidentCompany.objects.create(
            name="Acme MMC", slug="acme-mmc", status="active", is_internal=False
        )
        self.client.force_login(self.manager)
        paths = [
            reverse("erp:dashboard"),
            reverse("erp:residents"),
            reverse("erp:resident_detail", kwargs={"slug": tenant.slug}),
            reverse("erp:tickets"),
            reverse("erp:documents"),
            reverse("erp:spaces"),
            reverse("erp:warehouse"),
            reverse("erp:procurement"),
            reverse("erp:people_inside"),
            reverse("erp:reports"),
            reverse("erp:crm_leads"),
            reverse("erp:leases") + "?filter=expiring",
            reverse("erp:ar_aging"),
            reverse("erp:announcements"),
        ]
        for path in paths:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, msg=path)
            self.assertContains(resp, "cp-theme-mgmt", msg_prefix=path)

    def test_management_blocked_from_reception_and_space_create(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse("erp:reception"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("erp:dashboard"))

    def test_management_cannot_mutate_tickets(self):
        from apps.tickets.access import can_mutate_ticket

        class _T:
            pass

        self.assertFalse(can_mutate_ticket(self.manager, _T()))

    def test_open_wo_kpi_matches_fm_drill(self):
        today = timezone.localdate()
        open_wo = WorkOrder.objects.create(
            code="WO-OPEN-1",
            title="Open KPI",
            status=WorkOrderStatus.OPEN,
        )
        done = WorkOrder.objects.create(
            code="WO-DONE-1",
            title="Done KPI",
            status=WorkOrderStatus.COMPLETED,
            completed_at=timezone.now(),
        )
        hub = build_management_hub(self.manager)
        wo_kpi = next(k for k in hub["kpi_portfolio"] if "reports/drill/fm" in k["url"])
        self.assertIn(f"date_to={today.isoformat()}", wo_kpi["url"])
        self.assertGreaterEqual(wo_kpi["value"], 1)

        self.client.force_login(self.manager)
        drill = self.client.get(wo_kpi["url"])
        self.assertEqual(drill.status_code, 200)
        self.assertEqual(drill.context["data"]["open_wo"], wo_kpi["value"])
        codes = {r["code"] for r in drill.context["data"]["open_wo_rows"]}
        self.assertIn(open_wo.code, codes)
        self.assertNotIn(done.code, codes)

    def test_upcoming_events_30_day_vs_lease_kpi_90(self):
        today = timezone.localdate()
        party = Party.objects.create(
            party_type=PartyType.ORGANIZATION,
            legal_name="Agenda Co",
            status=PartyStatus.ACTIVE,
        )
        building = Building.objects.create(code="AGB", name="AGB")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        space = Space.objects.create(code="AG-S1", name="S1", floor=floor, area_m2=Decimal("50"))
        in_30 = Lease.objects.create(
            code="LS-IN30",
            party=party,
            space=space,
            status=LeaseStatus.ACTIVE,
            start_date=today - timedelta(days=100),
            end_date=today + timedelta(days=30),
            rent=Decimal("100"),
        )
        space2 = Space.objects.create(code="AG-S2", name="S2", floor=floor, area_m2=Decimal("50"))
        in_90 = Lease.objects.create(
            code="LS-IN90",
            party=party,
            space=space2,
            status=LeaseStatus.ACTIVE,
            start_date=today - timedelta(days=100),
            end_date=today + timedelta(days=60),
            rent=Decimal("100"),
        )
        hub = build_management_hub(self.manager)
        event_codes = {e["title"] for e in hub["upcoming_events"] if e["kind"]}
        self.assertIn(in_30.code, event_codes)
        self.assertNotIn(in_90.code, event_codes)
        lease_kpi = next(k for k in hub["kpi_portfolio"] if "90" in str(k["label"]) or "Bitən" in str(k["label"]))
        self.assertGreaterEqual(lease_kpi["value"], 2)
        self.assertEqual(hub["upcoming_events_days"], 30)
        self.assertIn("Asia/Baku", hub["upcoming_events_period_label"])

    def test_crm_report_single_active_nav(self):
        groups = build_management_nav(self.manager, url_name="crm_reports")
        active_items = [
            (g["key"], i["label"], i["url"])
            for g in groups
            for i in g["items"]
            if i["is_active"]
        ]
        self.assertEqual(len(active_items), 1)
        self.assertEqual(active_items[0][0], "reports")
        reports_g = next(g for g in groups if g["key"] == "reports")
        self.assertTrue(reports_g["is_active"])
        commercial = next(g for g in groups if g["key"] == "commercial")
        self.assertFalse(commercial["is_active"])
        # Shortcut still present under commercial
        self.assertTrue(any("crm/reports" in i["url"] for i in commercial["items"]))

    def test_building_kpi_counts_and_list_parity(self):
        from apps.crm.dashboard import available_spaces_qs
        from apps.erp.management_hub import building_register_snapshot
        from apps.parties.services import PartyService
        from apps.property.models import CommercialStatus, Occupancy, OperationalStatus
        from apps.residents.models import ResidentCompany

        today = timezone.localdate()
        company = ResidentCompany.objects.create(
            name="Multi Office MMC",
            slug="multi-office-kpi",
            status="active",
            is_internal=False,
        )
        party = PartyService.upsert_from_resident_company(company, audit=False)
        building = Building.objects.create(code="BKP", name="BKP")
        floor = Floor.objects.create(building=building, code="F1", name="1")
        s1 = Space.objects.create(
            code="BKP-1",
            name="O1",
            floor=floor,
            area_m2=Decimal("40"),
            rentable_area_m2=Decimal("40"),
            commercial_status=CommercialStatus.ACTIVE,
            occupancy=Occupancy.ACTIVE_LEASE,
            operational_status=OperationalStatus.AVAILABLE,
            resident=company,
        )
        s2 = Space.objects.create(
            code="BKP-2",
            name="O2",
            floor=floor,
            area_m2=Decimal("45"),
            rentable_area_m2=Decimal("45"),
            commercial_status=CommercialStatus.ACTIVE,
            occupancy=Occupancy.ACTIVE_LEASE,
            operational_status=OperationalStatus.AVAILABLE,
            resident=company,
        )
        # Future reservation — register "reserved", not occupied
        reserved = Space.objects.create(
            code="BKP-R",
            name="Reserved",
            floor=floor,
            area_m2=Decimal("30"),
            rentable_area_m2=Decimal("30"),
            commercial_status=CommercialStatus.RESERVED,
            occupancy=Occupancy.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
        )
        # Blocked — excluded from inventory denominator
        Space.objects.create(
            code="BKP-X",
            name="Blocked",
            floor=floor,
            area_m2=Decimal("20"),
            rentable_area_m2=Decimal("20"),
            commercial_status=CommercialStatus.VACANT,
            occupancy=Occupancy.VACANT,
            operational_status=OperationalStatus.BLOCKED,
        )
        ready = Space.objects.create(
            code="BKP-V",
            name="Ready",
            floor=floor,
            area_m2=Decimal("55"),
            rentable_area_m2=Decimal("55"),
            commercial_status=CommercialStatus.VACANT,
            occupancy=Occupancy.VACANT,
            operational_status=OperationalStatus.AVAILABLE,
        )
        Lease.objects.create(
            code="LS-BKP-1",
            party=party,
            space=s1,
            status=LeaseStatus.ACTIVE,
            start_date=today - timedelta(days=10),
            end_date=today + timedelta(days=200),
            rent=Decimal("100"),
        )
        Lease.objects.create(
            code="LS-BKP-FUT",
            party=party,
            space=reserved,
            status=LeaseStatus.SIGNED,
            start_date=today + timedelta(days=30),
            end_date=today + timedelta(days=400),
            rent=Decimal("100"),
        )

        snap = building_register_snapshot(as_of=today)
        self.assertIn(s1.pk, snap["occupied_ids"])
        self.assertIn(s2.pk, snap["occupied_ids"])
        self.assertNotIn(reserved.pk, snap["occupied_ids"])
        self.assertNotIn(
            next(s.pk for s in Space.objects.filter(code="BKP-X")),
            snap["denominator_ids"],
        )
        self.assertEqual(snap["occupying_resident_count"], 1)

        hub = build_management_hub(self.manager)
        by_key = {k["key"]: k for k in hub["building_kpis"]}
        self.assertEqual(by_key["residents"]["value"], snap["occupying_resident_count"])
        self.assertEqual(by_key["spaces_occupied"]["value"], snap["occupied_count"])
        self.assertEqual(by_key["spaces_total"]["value"], snap["denominator_count"])
        self.assertIn("status=occupied", by_key["spaces_occupied"]["url"])
        self.assertIn("mgmt=rentable", by_key["spaces_total"]["url"])
        self.assertIn("occupying=1", by_key["residents"]["url"])
        self.assertIn("m²", by_key["spaces_occupied"]["meta"])
        # Occupancy chip uses register m² (same as building KPIs), not sparse Lease as-of.
        expected_pct = round(
            100 * float(snap["occupied_m2"]) / float(snap["total_m2"]), 1
        )
        self.assertEqual(hub["occupancy_pct"], f"{expected_pct}%")
        self.assertIn("Reyestr", hub["property_rule"])

        ready_qs, _ = available_spaces_qs(today=today)
        self.assertEqual(by_key["spaces_ready"]["value"], ready_qs.count())
        self.assertTrue(ready_qs.filter(pk=ready.pk).exists())

        self.client.force_login(self.manager)
        residents = self.client.get(by_key["residents"]["url"])
        self.assertEqual(residents.status_code, 200)
        self.assertEqual(residents.context["companies"].count(), by_key["residents"]["value"])

        occupied_list = self.client.get(by_key["spaces_occupied"]["url"])
        self.assertEqual(occupied_list.status_code, 200)
        self.assertEqual(
            occupied_list.context["occupied_count"],
            by_key["spaces_occupied"]["value"],
        )

        rentable_list = self.client.get(by_key["spaces_total"]["url"])
        self.assertEqual(rentable_list.status_code, 200)
        self.assertEqual(
            rentable_list.context["mgmt_filtered_count"],
            by_key["spaces_total"]["value"],
        )

        ready_list = self.client.get(by_key["spaces_ready"]["url"])
        self.assertEqual(ready_list.status_code, 200)
        self.assertEqual(ready_list.context["space_count"], by_key["spaces_ready"]["value"])

        dash = self.client.get(reverse("erp:dashboard"))
        self.assertEqual(dash.status_code, 200)
        for card in dash.context["building_kpis"]:
            self.assertIsInstance(card["value"], int)
        self.assertContains(dash, "Rezident şirkətlər")
        self.assertRegex(dash.content.decode("utf-8"), r'mgmt-decision-count">0<')
