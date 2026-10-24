from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.services import DomainError
from apps.warehouse.models import (
    IssueStatus,
    Stock,
    StockMovement,
    StockMovementType,
    WarehouseIssue,
    WarehouseIssueLine,
)


SIGNED_DELTAS = {
    StockMovementType.RECEIPT: Decimal("1"),
    StockMovementType.RETURN: Decimal("1"),
    StockMovementType.RELEASE: Decimal("1"),
    StockMovementType.ISSUE: Decimal("-1"),
    StockMovementType.RESERVATION: Decimal("-1"),
    StockMovementType.TRANSFER: Decimal("-1"),
    StockMovementType.ADJUSTMENT: Decimal("1"),
}


@transaction.atomic
def apply_movement(
    *,
    sku,
    warehouse,
    movement_type,
    quantity,
    bin=None,
    reference="",
    work_order=None,
    notes="",
) -> StockMovement:
    qty = Decimal(quantity)
    if qty < 0:
        raise ValueError("quantity must be non-negative")

    movement = StockMovement.objects.create(
        sku=sku,
        warehouse=warehouse,
        movement_type=movement_type,
        quantity=qty,
        reference=reference or "",
        work_order=work_order,
        notes=notes or "",
    )

    stock, _ = Stock.objects.select_for_update().get_or_create(
        sku=sku,
        warehouse=warehouse,
        bin=bin,
        defaults={"quantity": Decimal("0")},
    )
    sign = SIGNED_DELTAS.get(movement_type, Decimal("1"))
    if movement_type == StockMovementType.ADJUSTMENT:
        stock.quantity = qty
    else:
        new_qty = (stock.quantity or Decimal("0")) + (sign * qty)
        if new_qty < 0:
            raise ValueError("Insufficient stock")
        stock.quantity = new_qty
    stock.save(update_fields=["quantity"])
    return movement


def can_confirm_warehouse_issue(user) -> bool:
    from apps.accounts.models import Role

    return getattr(user, "role", None) in {Role.ADMIN, Role.MANAGEMENT}


def _next_issue_code() -> str:
    codes = WarehouseIssue.objects.filter(code__startswith="WX-").values_list("code", flat=True)
    numbers = []
    for code in codes:
        try:
            numbers.append(int(str(code).split("-")[1]))
        except (IndexError, ValueError):
            continue
    nxt = (max(numbers) + 1) if numbers else 1001
    return f"WX-{nxt}"


@transaction.atomic
def request_issue_line(*, work_order, warehouse, sku, quantity, actor) -> WarehouseIssue:
    qty = Decimal(quantity)
    if qty <= 0:
        raise DomainError("Miqdar sıfırdan böyük olmalıdır.")
    issue = (
        WarehouseIssue.objects.select_for_update()
        .filter(work_order=work_order, warehouse=warehouse, status=IssueStatus.OPEN)
        .first()
    )
    if issue is None:
        issue = WarehouseIssue.objects.create(
            code=_next_issue_code(),
            work_order=work_order,
            warehouse=warehouse,
            status=IssueStatus.OPEN,
            requested_by=actor,
        )
    line = issue.lines.filter(sku=sku).first()
    if line is None:
        WarehouseIssueLine.objects.create(issue=issue, sku=sku, requested_qty=qty)
    else:
        line.requested_qty = (line.requested_qty or Decimal("0")) + qty
        line.save(update_fields=["requested_qty"])
    return issue


@transaction.atomic
def confirm_issue(issue, *, actor, lines) -> WarehouseIssue:
    from apps.maintenance.costs import line_amount, refresh_cost_totals
    from apps.maintenance.models import CostLineKind, CostLineSource, WorkOrderCostLine

    locked = WarehouseIssue.objects.select_for_update().get(pk=issue.pk)
    if locked.status != IssueStatus.OPEN:
        raise DomainError("Sənəd artıq təsdiqlənib.")
    posted = {row["id"]: row for row in lines}
    for line in locked.lines.select_related("sku"):
        row = posted.get(line.pk)
        if row is None:
            raise DomainError("Hər sətir üçün faktiki miqdar yazılmalıdır.")
        issued = Decimal(row["issued_qty"])
        unit_cost = Decimal(row["unit_cost"])
        if issued < 0 or unit_cost < 0:
            raise DomainError("Miqdar və qiymət mənfi ola bilməz.")
        if issued > line.requested_qty:
            raise DomainError("Faktiki miqdar tələb olunan miqdardan çox ola bilməz.")
        line.issued_qty = issued
        line.unit_cost = unit_cost
        line.save(update_fields=["issued_qty", "unit_cost"])
        if issued <= 0:
            continue
        apply_movement(
            sku=line.sku,
            warehouse=locked.warehouse,
            movement_type=StockMovementType.ISSUE,
            quantity=issued,
            reference=locked.code,
            work_order=locked.work_order,
        )
        WorkOrderCostLine.objects.update_or_create(
            warehouse_issue_line=line,
            defaults={
                "work_order": locked.work_order,
                "kind": CostLineKind.MATERIAL,
                "source": CostLineSource.WAREHOUSE,
                "description": f"{line.sku.code} — {line.sku.name}"[:255],
                "qty": issued,
                "unit": (line.sku.unit or "ədəd")[:16],
                "unit_price": unit_cost,
                "amount": line_amount(issued, unit_cost),
            },
        )
    locked.status = IssueStatus.ISSUED
    locked.issued_by = actor
    locked.issued_at = timezone.now()
    locked.save(update_fields=["status", "issued_by", "issued_at"])
    refresh_cost_totals(locked.work_order)
    return locked
