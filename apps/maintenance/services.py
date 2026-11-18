from datetime import timedelta
from calendar import monthrange

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Charge, ChargeSource
from apps.core import events as bus
from apps.core.services import Service
from apps.maintenance.models import (
    Inspection,
    MaintenancePlan,
    PlanFrequency,
    WorkOrder,
    WorkOrderPriority,
    WorkOrderStatus,
)
from apps.parties.resolvers import party_for_company


def next_wo_code():
    codes = WorkOrder.objects.filter(code__startswith="WO-").values_list("code", flat=True)
    numbers = []
    for code in codes:
        try:
            numbers.append(int(code.split("-")[1]))
        except (IndexError, ValueError):
            continue
    nxt = (max(numbers) + 1) if numbers else 1001
    return f"WO-{nxt}"


def create_wo_from_ticket(ticket) -> WorkOrder:
    priority_map = {
        "low": WorkOrderPriority.LOW,
        "normal": WorkOrderPriority.NORMAL,
        "high": WorkOrderPriority.HIGH,
    }
    priority = priority_map.get(getattr(ticket, "priority", None), WorkOrderPriority.NORMAL)
    title = f"WO for {ticket.code}"
    description = getattr(ticket, "description", "") or ""
    return WorkOrder.objects.create(
        code=next_wo_code(),
        title=title,
        description=description,
        status=WorkOrderStatus.OPEN,
        priority=priority,
        space=getattr(ticket, "space", None),
        ticket=ticket,
        assigned_to=getattr(ticket, "assignee", None),
    )


def sync_ticket_from_work_order(wo: WorkOrder, *, actor=None) -> None:
    """When the last open WO for a ticket completes, advance ticket to RESOLVED."""
    if not wo.ticket_id or wo.status != WorkOrderStatus.COMPLETED:
        return
    ticket = wo.ticket
    from apps.tickets.models import OPEN_STATUSES, TicketStatus
    from apps.tickets.services import can_transition_to, set_ticket_status

    open_siblings = (
        WorkOrder.objects.filter(ticket_id=ticket.pk)
        .exclude(pk=wo.pk)
        .exclude(status__in=(WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED))
    )
    if open_siblings.exists():
        return
    if ticket.status not in OPEN_STATUSES:
        return
    note = f"WO {wo.code} tamamlandı"
    # actor=None: system sync must not be blocked by mutate ACL
    for step in (
        TicketStatus.ACCEPTED,
        TicketStatus.IN_PROGRESS,
        TicketStatus.RESOLVED,
    ):
        ticket.refresh_from_db()
        if ticket.status == TicketStatus.RESOLVED:
            break
        if can_transition_to(ticket, step):
            set_ticket_status(ticket, step, actor=None, note=note)


class WorkOrderService(Service):
    @classmethod
    @transaction.atomic
    def set_status(cls, wo: WorkOrder, status: str, *, actor=None) -> WorkOrder:
        allowed = {c.value for c in WorkOrderStatus}
        cls.require(status in allowed, "Naməlum WO status.")
        wo.status = status
        update = ["status"]
        if status == WorkOrderStatus.COMPLETED:
            wo.completed_at = timezone.now()
            update.append("completed_at")
            amount = wo.resident_amount
            if wo.billable and amount and amount > 0:
                party = wo.party
                if not party and wo.ticket_id and wo.ticket.company_id:
                    party = party_for_company(wo.ticket.company, ensure=True)
                if party and not wo.charges.filter(source=ChargeSource.WORK_ORDER).exists():
                    Charge.objects.create(
                        party=party,
                        space=wo.space,
                        source=ChargeSource.WORK_ORDER,
                        description=f"İş sifarişi {wo.code}",
                        amount=amount,
                        work_order=wo,
                    )
            bus.emit(
                bus.WORK_ORDER_CLOSED,
                payload={"work_order_id": wo.pk, "code": wo.code},
                actor=actor,
            )
        wo.save(update_fields=update)
        if status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
            sync_ticket_from_work_order(wo, actor=actor)
            if status == WorkOrderStatus.COMPLETED:
                _log_repair_for_wo(wo, actor=actor)
        return wo


def _add_months(value, months: int):
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def advance_plan_due(plan: MaintenancePlan, *, from_date=None):
    """Compute next due date from frequency."""
    start = from_date or plan.next_due or timezone.localdate()
    freq = plan.frequency
    if freq == PlanFrequency.DAILY:
        return start + timedelta(days=1)
    if freq == PlanFrequency.WEEKLY:
        return start + timedelta(days=7)
    if freq == PlanFrequency.MONTHLY:
        return _add_months(start, 1)
    if freq == PlanFrequency.QUARTERLY:
        return _add_months(start, 3)
    if freq == PlanFrequency.YEARLY:
        return _add_months(start, 12)
    # meter / unknown — leave unchanged so ops can set manually
    return start


def _log_repair_for_wo(wo: WorkOrder, *, actor=None) -> None:
    if not wo.building_asset_id:
        return
    from apps.property.models import BuildingAssetEvent, BuildingAssetEventType

    BuildingAssetEvent.objects.create(
        asset_id=wo.building_asset_id,
        event_type=BuildingAssetEventType.REPAIR,
        summary=f"{wo.code} tamamlandı",
        notes=(wo.title or "")[:500],
        work_order=wo,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
    )


def generate_work_orders_for_due_plans(*, as_of=None, actor=None) -> dict:
    """Create OPEN work orders for every active MaintenancePlan due on/before as_of."""
    as_of = as_of or timezone.localdate()
    stats = {"checked": 0, "created": 0, "advanced": 0, "skipped": 0}
    plans = (
        MaintenancePlan.objects.filter(is_active=True, next_due__isnull=False, next_due__lte=as_of)
        .select_related("asset", "building_asset", "space")
        .order_by("next_due", "id")
    )
    for plan in plans:
        stats["checked"] += 1
        # One open PM WO per plan (avoid duplicates if poller re-runs same day).
        open_exists = WorkOrder.objects.filter(
            title__startswith=f"PM:{plan.pk}:",
            status__in=(
                WorkOrderStatus.OPEN,
                WorkOrderStatus.ASSIGNED,
                WorkOrderStatus.IN_PROGRESS,
            ),
        ).exists()
        if open_exists:
            stats["skipped"] += 1
            continue
        with transaction.atomic():
            space = plan.space
            if space is None and plan.asset_id:
                space = plan.asset.space
            title = f"PM:{plan.pk}: {plan.name}"[:200]
            wo = WorkOrder.objects.create(
                code=next_wo_code(),
                title=title,
                description=f"Preventive maintenance — {plan.get_frequency_display()}",
                status=WorkOrderStatus.OPEN,
                priority=WorkOrderPriority.NORMAL,
                space=space,
                asset=plan.asset,
                building_asset=plan.building_asset,
                scheduled_for=plan.next_due,
            )
            Inspection.objects.create(
                plan=plan,
                space=space,
                building_asset=plan.building_asset,
                work_order=wo,
                result="scheduled",
                notes=plan.name,
            )
            if plan.building_asset_id:
                from apps.property.models import BuildingAssetEvent, BuildingAssetEventType

                BuildingAssetEvent.objects.create(
                    asset=plan.building_asset,
                    event_type=BuildingAssetEventType.INSPECTION,
                    summary=f"PM WO {wo.code}",
                    notes=plan.name,
                    work_order=wo,
                    actor=actor if getattr(actor, "is_authenticated", False) else None,
                )
            plan.next_due = advance_plan_due(plan, from_date=plan.next_due)
            plan.save(update_fields=["next_due"])
            stats["created"] += 1
            stats["advanced"] += 1
    return stats


def confirm_inspection(inspection: Inspection, *, actor, result: str = "", notes: str = "") -> Inspection:
    """Record inspection outcome and optional completion confirmation."""
    inspection.result = (result or inspection.result or "ok")[:64]
    if notes:
        inspection.notes = notes
    inspection.confirmed_at = timezone.now()
    inspection.confirmed_by = actor if getattr(actor, "is_authenticated", False) else None
    inspection.save(update_fields=["result", "notes", "confirmed_at", "confirmed_by"])
    if inspection.building_asset_id:
        from apps.property.models import BuildingAssetEvent, BuildingAssetEventType

        BuildingAssetEvent.objects.create(
            asset_id=inspection.building_asset_id,
            event_type=BuildingAssetEventType.INSPECTION,
            summary=inspection.result or "baxış",
            notes=inspection.notes or "",
            work_order=inspection.work_order,
            actor=inspection.confirmed_by,
        )
        asset = inspection.building_asset
        asset.last_inspected_on = timezone.localdate()
        asset.next_inspection_on = _add_months(asset.last_inspected_on, 1)
        asset.save(update_fields=["last_inspected_on", "next_inspection_on"])
    return inspection
