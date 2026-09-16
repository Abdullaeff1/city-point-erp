from apps.maintenance.models import WorkOrder, WorkOrderPriority, WorkOrderStatus


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
