from datetime import timedelta
from calendar import monthrange

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Charge, ChargeSource
from apps.core import events as bus
from apps.core.services import DomainError, Service
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


ACTIVE_WO_STATUSES = (
    WorkOrderStatus.OPEN,
    WorkOrderStatus.ASSIGNED,
    WorkOrderStatus.IN_PROGRESS,
)


def ticket_has_active_work_order(ticket, *, exclude_pk=None) -> bool:
    qs = WorkOrder.objects.filter(ticket_id=ticket.pk, status__in=ACTIVE_WO_STATUSES)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def create_work_order(
    *,
    title: str,
    description: str = "",
    priority: str = WorkOrderPriority.NORMAL,
    space=None,
    asset=None,
    building_asset=None,
    contractor=None,
    party=None,
    ticket=None,
    assigned_to=None,
    scheduled_for=None,
    actor=None,
) -> WorkOrder:
    """Create a Work Order. Ticket may be None for Facility-originated / PM work."""
    from apps.core import events as bus

    title = (title or "").strip()
    if not title:
        raise DomainError("Başlıq tələb olunur.")
    allowed_priority = {c.value for c in WorkOrderPriority}
    if priority not in allowed_priority:
        priority = WorkOrderPriority.NORMAL

    with transaction.atomic():
        wo = WorkOrder.objects.create(
            code=next_wo_code(),
            title=title[:200],
            description=(description or "").strip(),
            status=WorkOrderStatus.OPEN,
            priority=priority,
            space=space,
            asset=asset,
            building_asset=building_asset,
            contractor=contractor,
            party=party,
            ticket=ticket,
            assigned_to=assigned_to,
            scheduled_for=scheduled_for,
        )
        bus.emit(
            bus.WORK_ORDER_CREATED,
            payload={
                "work_order_id": wo.pk,
                "code": wo.code,
                "ticket_id": wo.ticket_id,
                "entity_model": "work_order",
                "standalone": wo.ticket_id is None,
            },
            actor=actor,
            event_key=f"wo.created.{wo.pk}",
        )
    return wo


def create_wo_from_ticket(ticket) -> WorkOrder:
    """Create WO linked to ticket. Do not copy ticket.assignee — Facility assigns via routing.

    Event emission is owned by ``create_work_order_from_ticket`` (tickets layer).
    """
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
        assigned_to=None,
    )


def create_standalone_work_order(
    *,
    title: str,
    description: str = "",
    priority: str = WorkOrderPriority.NORMAL,
    space=None,
    asset=None,
    building_asset=None,
    contractor=None,
    party=None,
    assigned_to=None,
    scheduled_for=None,
    actor=None,
) -> WorkOrder:
    """Facility-originated WO with no Helpdesk ticket."""
    from apps.maintenance.access import can_create_standalone_work_order

    if not can_create_standalone_work_order(actor):
        raise DomainError("İş sifarişi yaratmaq icazəniz yoxdur.")
    return create_work_order(
        title=title,
        description=description,
        priority=priority,
        space=space,
        asset=asset,
        building_asset=building_asset,
        contractor=contractor,
        party=party,
        ticket=None,
        assigned_to=assigned_to,
        scheduled_for=scheduled_for,
        actor=actor,
    )


def facility_work_order_assignees():
    """Active Facility operators eligible for WO assignment."""
    from django.contrib.auth import get_user_model

    from apps.accounts.models import Role

    User = get_user_model()
    return User.objects.filter(role=Role.PROPERTY_FM, is_active=True).order_by(
        "first_name", "last_name", "username"
    )


@transaction.atomic
def assign_work_order(wo: WorkOrder, *, actor, assignee_id=None) -> WorkOrder:
    """Assign / reassign a Work Order to a Facility operator.

    Emits ``WorkOrderAssigned`` once per successful change (event_key includes assignee).
    OPEN → ASSIGNED when an assignee is set.
    """
    from apps.maintenance.access import can_mutate_work_order

    # Do not select_related nullable ticket — Postgres rejects FOR UPDATE on outer joins.
    wo = WorkOrder.objects.select_for_update().get(pk=wo.pk)
    if not can_mutate_work_order(actor, wo):
        raise DomainError("İş sifarişini təyin etmək icazəniz yoxdur.")
    if wo.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
        raise DomainError("Bağlı iş sifarişinə təyinat edilə bilməz.")

    assignee = None
    if assignee_id:
        assignee = facility_work_order_assignees().filter(pk=assignee_id).first()
        if assignee is None:
            raise DomainError("Təyinat yalnız Facility operatoruna mümkündür.")

    previous_id = wo.assigned_to_id
    if previous_id == (assignee.pk if assignee else None):
        return wo

    wo.assigned_to = assignee
    update = ["assigned_to"]
    if assignee and wo.status == WorkOrderStatus.OPEN:
        wo.status = WorkOrderStatus.ASSIGNED
        update.append("status")
    wo.save(update_fields=update)

    if assignee:
        bus.emit(
            bus.WORK_ORDER_ASSIGNED,
            payload={
                "work_order_id": wo.pk,
                "code": wo.code,
                "ticket_id": wo.ticket_id,
                "assignee_id": assignee.pk,
                "previous_assignee_id": previous_id,
                "entity_model": "work_order",
            },
            actor=actor,
            event_key=f"wo.assigned.{wo.pk}.{assignee.pk}",
        )
    return wo


def sync_ticket_from_work_order(wo: WorkOrder, *, actor=None) -> None:
    """On last active WO completion: progress ticket at most to IN_PROGRESS — never RESOLVED/CLOSED.

    Helpdesk confirms final ticket resolution. Respects can_transition_to at each step.
    """
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
    note = f"WO {wo.code} tamamlandı — Helpdesk təsdiqi gözlənilir"
    # actor=None: system sync must not be blocked by mutate ACL
    for step in (TicketStatus.ACCEPTED, TicketStatus.IN_PROGRESS):
        ticket.refresh_from_db()
        if ticket.status == TicketStatus.IN_PROGRESS:
            break
        if can_transition_to(ticket, step):
            set_ticket_status(ticket, step, actor=None, note=note)


class WorkOrderService(Service):
    @classmethod
    @transaction.atomic
    def set_status(cls, wo: WorkOrder, status: str, *, actor=None, note: str = "") -> WorkOrder:
        allowed = {c.value for c in WorkOrderStatus}
        cls.require(status in allowed, "Naməlum WO status.")
        wo = WorkOrder.objects.select_for_update().get(pk=wo.pk)
        if wo.status == status and status != WorkOrderStatus.COMPLETED:
            return wo
        # Idempotent complete: keep first completed_at and do not re-emit.
        if status == WorkOrderStatus.COMPLETED and wo.status == WorkOrderStatus.COMPLETED:
            return wo
        previous = wo.status
        wo.status = status
        update = ["status"]
        tech_note = (note or "").strip()
        if status == WorkOrderStatus.COMPLETED:
            wo.completed_at = timezone.now()
            update.append("completed_at")
            if tech_note and "[Texniki nəticə]" not in (wo.description or ""):
                wo.description = (
                    (wo.description or "").rstrip() + "\n\n[Texniki nəticə]\n" + tech_note
                ).strip()
                update.append("description")
            amount = wo.resident_amount
            if wo.billable and amount and amount > 0:
                party = wo.party
                ticket = wo.ticket if wo.ticket_id else None
                if not party and ticket is not None and ticket.company_id:
                    party = party_for_company(ticket.company, ensure=True)
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
                payload={
                    "work_order_id": wo.pk,
                    "code": wo.code,
                    "ticket_id": wo.ticket_id,
                    "entity_model": "work_order",
                    "previous_status": previous,
                    "note": tech_note[:500] if tech_note else "",
                },
                actor=actor,
                event_key=f"wo.closed.{wo.pk}",
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


@transaction.atomic
def create_maintenance_plan(
    *,
    name: str,
    frequency: str = PlanFrequency.MONTHLY,
    next_due=None,
    building_asset=None,
    asset=None,
    space=None,
    is_active: bool = True,
    actor=None,
) -> MaintenancePlan:
    """FM creates a preventive plan from the ERP UI (Admin-only before)."""
    from apps.audit.services import log_action

    name = (name or "").strip()
    if not name:
        raise DomainError("Plan adı tələb olunur.")
    allowed = {c.value for c in PlanFrequency}
    if frequency not in allowed:
        raise DomainError("Tezlik düzgün deyil.")
    if not building_asset and not asset and not space:
        raise DomainError("Ən azı avadanlıq və ya sahə seçilməlidir.")
    due = next_due or timezone.localdate()
    plan = MaintenancePlan.objects.create(
        name=name[:200],
        frequency=frequency,
        next_due=due,
        building_asset=building_asset,
        asset=asset,
        space=space,
        is_active=bool(is_active),
    )
    log_action(
        actor=actor,
        action="maintenance.plan.create",
        entity=plan,
        message=f"{plan.name} · {plan.frequency} · due {plan.next_due}",
    )
    return plan


@transaction.atomic
def update_maintenance_plan(
    plan: MaintenancePlan,
    *,
    name: str | None = None,
    frequency: str | None = None,
    next_due=None,
    building_asset=None,
    asset=None,
    space=None,
    is_active: bool | None = None,
    actor=None,
    clear_targets: bool = False,
) -> MaintenancePlan:
    from apps.audit.services import log_action

    plan = MaintenancePlan.objects.select_for_update().get(pk=plan.pk)
    if name is not None:
        name = name.strip()
        if not name:
            raise DomainError("Plan adı tələb olunur.")
        plan.name = name[:200]
    if frequency is not None:
        allowed = {c.value for c in PlanFrequency}
        if frequency not in allowed:
            raise DomainError("Tezlik düzgün deyil.")
        plan.frequency = frequency
    if next_due is not None:
        plan.next_due = next_due
    if clear_targets:
        plan.building_asset = building_asset
        plan.asset = asset
        plan.space = space
    else:
        if building_asset is not None:
            plan.building_asset = building_asset
        if asset is not None:
            plan.asset = asset
        if space is not None:
            plan.space = space
    if is_active is not None:
        plan.is_active = bool(is_active)
    if not plan.building_asset_id and not plan.asset_id and not plan.space_id:
        raise DomainError("Ən azı avadanlıq və ya sahə seçilməlidir.")
    plan.save()
    log_action(
        actor=actor,
        action="maintenance.plan.update",
        entity=plan,
        message=f"{plan.name} · active={plan.is_active} · due {plan.next_due}",
    )
    return plan


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
    from apps.audit.services import log_action

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
            bus.emit(
                bus.WORK_ORDER_CREATED,
                payload={
                    "work_order_id": wo.pk,
                    "code": wo.code,
                    "ticket_id": None,
                    "entity_model": "work_order",
                    "standalone": True,
                    "pm_plan_id": plan.pk,
                },
                actor=actor,
                event_key=f"wo.created.{wo.pk}",
            )
    if stats["created"]:
        log_action(
            actor=actor,
            action="maintenance.plan.generate",
            new_values=stats,
            message=f"PM generate as_of={as_of}: created={stats['created']}",
        )
    return stats


@transaction.atomic
def confirm_inspection(inspection: Inspection, *, actor, result: str = "", notes: str = "") -> Inspection:
    """Record inspection outcome and optional completion confirmation."""
    from apps.audit.services import log_action

    inspection = Inspection.objects.select_for_update().get(pk=inspection.pk)
    if inspection.confirmed_at:
        return inspection
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
    log_action(
        actor=actor,
        action="maintenance.inspection.confirm",
        entity=inspection,
        message=inspection.result,
    )
    return inspection
