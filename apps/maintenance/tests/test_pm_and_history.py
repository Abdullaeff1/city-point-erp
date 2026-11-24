from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role
from apps.maintenance.models import (
    Inspection,
    MaintenancePlan,
    PlanFrequency,
    WorkOrder,
    WorkOrderStatus,
)
from apps.maintenance.services import (
    WorkOrderService,
    advance_plan_due,
    confirm_inspection,
    generate_work_orders_for_due_plans,
)
from apps.property.models import (
    BuildingAsset,
    BuildingAssetEvent,
    BuildingAssetEventType,
    BuildingAssetKind,
)

User = get_user_model()


class PreventiveMaintenanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="fm1", email="fm1@test.az", password="x", role=Role.SERVICE_DESK
        )
        self.asset = BuildingAsset.objects.create(
            name="AHU-1",
            kind=BuildingAssetKind.EQUIPMENT,
            manufacturer="Carrier",
            serial_number="SN-1",
            warranty_until=timezone.localdate() + timedelta(days=365),
        )

    def test_advance_frequencies(self):
        start = timezone.localdate().replace(day=15)
        plan = MaintenancePlan(name="x", frequency=PlanFrequency.WEEKLY, next_due=start)
        self.assertEqual(advance_plan_due(plan, from_date=start), start + timedelta(days=7))
        plan.frequency = PlanFrequency.MONTHLY
        nxt = advance_plan_due(plan, from_date=start)
        self.assertEqual((nxt.year, nxt.month), (start.year + (1 if start.month == 12 else 0), 1 if start.month == 12 else start.month + 1))
        plan.frequency = PlanFrequency.YEARLY
        self.assertEqual(advance_plan_due(plan, from_date=start).year, start.year + 1)

    def test_generate_wo_from_due_plan(self):
        today = timezone.localdate()
        plan = MaintenancePlan.objects.create(
            name="AHU filter",
            frequency=PlanFrequency.MONTHLY,
            building_asset=self.asset,
            next_due=today,
            is_active=True,
        )
        stats = generate_work_orders_for_due_plans(as_of=today)
        self.assertEqual(stats["created"], 1)
        wo = WorkOrder.objects.get()
        self.assertTrue(wo.title.startswith(f"PM:{plan.pk}:"))
        self.assertEqual(wo.building_asset_id, self.asset.pk)
        self.assertTrue(Inspection.objects.filter(work_order=wo, plan=plan).exists())
        self.assertTrue(
            BuildingAssetEvent.objects.filter(
                asset=self.asset, event_type=BuildingAssetEventType.INSPECTION
            ).exists()
        )
        plan.refresh_from_db()
        self.assertGreater(plan.next_due, today)
        # Second run same day should skip while WO open
        stats2 = generate_work_orders_for_due_plans(as_of=today)
        self.assertEqual(stats2["created"], 0)
        self.assertEqual(WorkOrder.objects.count(), 1)

    def test_confirm_inspection_and_wo_repair_event(self):
        today = timezone.localdate()
        plan = MaintenancePlan.objects.create(
            name="Lift PM",
            frequency=PlanFrequency.MONTHLY,
            building_asset=self.asset,
            next_due=today,
        )
        generate_work_orders_for_due_plans(as_of=today)
        wo = WorkOrder.objects.get()
        insp = Inspection.objects.get(work_order=wo)
        confirm_inspection(insp, actor=self.user, result="ok", notes="filter dəyişdi")
        insp.refresh_from_db()
        self.assertTrue(insp.confirmed_at)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.last_inspected_on, today)

        WorkOrderService.set_status(wo, WorkOrderStatus.COMPLETED, actor=self.user)
        self.assertTrue(
            BuildingAssetEvent.objects.filter(
                asset=self.asset, event_type=BuildingAssetEventType.REPAIR, work_order=wo
            ).exists()
        )
