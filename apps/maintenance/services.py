from django.db import transaction
from django.utils import timezone

from apps.billing.models import Charge, ChargeSource
from apps.core import events as bus
from apps.core.services import Service
from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus
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
        return wo
