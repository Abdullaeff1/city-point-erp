"""Master Phase 7 — MaintenancePlan / Inspection ERP UI."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.maintenance.models import Inspection, MaintenancePlan, PlanFrequency, WorkOrder
from apps.property.models import BuildingAsset, BuildingAssetKind
from apps.rbac.services import seed_rbac_catalog

User = get_user_model()


class MaintenancePlanUiTests(TestCase):
    def setUp(self):
        seed_rbac_catalog()
        self.client = Client()
        self.fm = User.objects.create_user(
            username="fm-pm",
            email="fm-pm@test.az",
            password="Pass12345!",
            role=Role.PROPERTY_FM,
            is_staff=True,
        )
        self.desk = User.objects.create_user(
            username="desk-pm",
            email="desk-pm@test.az",
            password="Pass12345!",
            role=Role.SERVICE_DESK,
            is_staff=True,
        )
        self.mgmt = User.objects.create_user(
            username="mgmt-pm",
            email="mgmt-pm@test.az",
            password="Pass12345!",
            role=Role.MANAGEMENT,
            is_staff=True,
        )
        self.asset = BuildingAsset.objects.create(
            name="AHU-Lobby",
            kind=BuildingAssetKind.EQUIPMENT,
        )

    def test_fm_creates_plan_generates_wo_and_confirms_inspection(self):
        self.client.force_login(self.fm)
        list_url = reverse("erp:maintenance_plans")
        self.assertEqual(self.client.get(list_url).status_code, 200)

        create = self.client.post(
            reverse("erp:maintenance_plan_create"),
            {
                "name": "AHU filter dəyişimi",
                "frequency": PlanFrequency.MONTHLY,
                "next_due": timezone.localdate().isoformat(),
                "building_asset": str(self.asset.pk),
                "is_active": "1",
            },
        )
        self.assertEqual(create.status_code, 302)
        plan = MaintenancePlan.objects.get(name="AHU filter dəyişimi")
        self.assertEqual(plan.building_asset_id, self.asset.pk)
        self.assertTrue(
            AuditLog.objects.filter(action="maintenance.plan.create", entity_id=plan.pk).exists()
        )

        gen = self.client.post(list_url, {"action": "generate"})
        self.assertEqual(gen.status_code, 302)
        wo = WorkOrder.objects.get()
        self.assertTrue(wo.title.startswith(f"PM:{plan.pk}:"))
        insp = Inspection.objects.get(work_order=wo)
        self.assertIsNone(insp.confirmed_at)

        detail = self.client.get(reverse("erp:work_order_detail", args=[wo.code]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Preventiv baxış")
        self.assertContains(detail, "Baxışı təsdiqlə")

        confirm = self.client.post(
            reverse("erp:work_order_detail", args=[wo.code]),
            {"action": "confirm_inspection", "result": "ok", "notes": "filtr dəyişildi"},
        )
        self.assertEqual(confirm.status_code, 302)
        insp.refresh_from_db()
        self.assertTrue(insp.confirmed_at)
        self.assertEqual(insp.confirmed_by_id, self.fm.pk)
        self.assertTrue(
            AuditLog.objects.filter(action="maintenance.inspection.confirm").exists()
        )

        # Repeat confirm preserves single confirmation (invariant).
        confirmed_at = insp.confirmed_at
        self.client.post(
            reverse("erp:work_order_detail", args=[wo.code]),
            {"action": "confirm_inspection", "result": "fail", "notes": "should ignore"},
        )
        insp.refresh_from_db()
        self.assertEqual(insp.confirmed_at, confirmed_at)
        self.assertEqual(insp.result, "ok")

        # Second generate while WO open skips duplicate.
        self.client.post(list_url, {"action": "generate"})
        self.assertEqual(WorkOrder.objects.count(), 1)

    def test_unauthorized_cannot_create_or_generate(self):
        self.client.force_login(self.desk)
        resp = self.client.get(reverse("erp:maintenance_plans"))
        # Helpdesk may lack facility role — soft-deny or 403/302.
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(MaintenancePlan.objects.exists())

        self.client.force_login(self.mgmt)
        page = self.client.get(reverse("erp:maintenance_plans"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, reverse("erp:maintenance_plan_create"))
        denied = self.client.post(
            reverse("erp:maintenance_plan_create"),
            {
                "name": "X",
                "frequency": PlanFrequency.WEEKLY,
                "next_due": timezone.localdate().isoformat(),
                "building_asset": str(self.asset.pk),
                "is_active": "1",
            },
        )
        self.assertIn(denied.status_code, (302, 403))
        self.assertFalse(MaintenancePlan.objects.filter(name="X").exists())

    def test_future_due_plan_does_not_generate(self):
        self.client.force_login(self.fm)
        MaintenancePlan.objects.create(
            name="Future",
            frequency=PlanFrequency.MONTHLY,
            building_asset=self.asset,
            next_due=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.client.post(reverse("erp:maintenance_plans"), {"action": "generate"})
        self.assertEqual(WorkOrder.objects.count(), 0)
