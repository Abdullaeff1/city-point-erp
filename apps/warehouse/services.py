from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.audit.services import log_action
from apps.core.services import DomainError
from apps.warehouse.models import (
    IssueStatus,
    SKU,
    Stock,
    StockMovement,
    StockMovementType,
    Warehouse,
    WarehouseIssue,
    WarehouseIssueLine,
)


SIGNED_DELTAS = {
    StockMovementType.RECEIPT: Decimal("1"),
    StockMovementType.RETURN: Decimal("1"),
    StockMovementType.ISSUE: Decimal("-1"),
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
        defaults={"quantity": Decimal("0"), "reserved_quantity": Decimal("0")},
    )
    if movement_type == StockMovementType.RESERVATION:
        available = (stock.quantity or Decimal("0")) - (stock.reserved_quantity or Decimal("0"))
        if qty > available:
            raise ValueError("Insufficient available stock")
        stock.reserved_quantity = (stock.reserved_quantity or Decimal("0")) + qty
        stock.save(update_fields=["reserved_quantity"])
        return movement
    if movement_type == StockMovementType.RELEASE:
        reserved = stock.reserved_quantity or Decimal("0")
        stock.reserved_quantity = reserved - qty if reserved >= qty else Decimal("0")
        stock.save(update_fields=["reserved_quantity"])
        return movement

    sign = SIGNED_DELTAS.get(movement_type, Decimal("1"))
    if movement_type == StockMovementType.ADJUSTMENT:
        reserved = stock.reserved_quantity or Decimal("0")
        if qty < reserved:
            raise ValueError("Adjustment cannot set quantity below reserved stock")
        stock.quantity = qty
        stock.save(update_fields=["quantity"])
        return movement
    new_qty = (stock.quantity or Decimal("0")) + (sign * qty)
    if new_qty < 0:
        raise ValueError("Insufficient stock")
    stock.quantity = new_qty
    # Physical issue also frees matching reservation.
    if movement_type == StockMovementType.ISSUE and (stock.reserved_quantity or 0) > 0:
        reserved = stock.reserved_quantity or Decimal("0")
        stock.reserved_quantity = reserved - qty if reserved >= qty else Decimal("0")
        stock.save(update_fields=["quantity", "reserved_quantity"])
    else:
        stock.save(update_fields=["quantity"])
    return movement


def can_confirm_warehouse_issue(user) -> bool:
    """Phase 4.2: permission-based; Management remains RO (no warehouse.edit)."""
    from apps.warehouse.access import can_mutate_warehouse

    return can_mutate_warehouse(user)


def _as_decimal(raw, *, field_label="Miqdar") -> Decimal:
    text = str(raw if raw is not None else "").strip().replace(" ", "").replace(",", ".")
    if text == "":
        raise DomainError(f"{field_label} tələb olunur.")
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError) as exc:
        raise DomainError(f"{field_label} rəqəm olmalıdır.") from exc
    return value


@transaction.atomic
def create_sku(*, code: str, name: str, unit: str = "pcs", reorder_level=0, actor=None) -> SKU:
    from apps.warehouse.access import can_mutate_warehouse

    if not can_mutate_warehouse(actor):
        raise DomainError("SKU yaratmaq icazəniz yoxdur.")
    code = (code or "").strip().upper()
    name = (name or "").strip()
    unit = ((unit or "pcs").strip() or "pcs")[:16]
    if not code:
        raise DomainError("SKU kodu tələb olunur.")
    if not name:
        raise DomainError("SKU adı tələb olunur.")
    reorder = _as_decimal(reorder_level, field_label="Minimum stok")
    if reorder < 0:
        raise DomainError("Minimum stok mənfi ola bilməz.")
    if SKU.objects.filter(code__iexact=code).exists():
        raise DomainError("Bu SKU kodu artıq mövcuddur.")
    sku = SKU.objects.create(code=code, name=name[:200], unit=unit, reorder_level=reorder)
    log_action(
        action="warehouse.sku.create",
        actor=actor,
        entity=sku,
        new_values={"code": sku.code, "name": sku.name, "reorder_level": str(sku.reorder_level)},
    )
    return sku


@transaction.atomic
def update_sku(sku: SKU, *, name: str, unit: str = "pcs", reorder_level=0, actor=None) -> SKU:
    from apps.warehouse.access import can_mutate_warehouse

    if not can_mutate_warehouse(actor):
        raise DomainError("SKU redaktə icazəniz yoxdur.")
    locked = SKU.objects.select_for_update().get(pk=sku.pk)
    name = (name or "").strip()
    unit = ((unit or locked.unit or "pcs").strip() or "pcs")[:16]
    if not name:
        raise DomainError("SKU adı tələb olunur.")
    reorder = _as_decimal(reorder_level, field_label="Minimum stok")
    if reorder < 0:
        raise DomainError("Minimum stok mənfi ola bilməz.")
    old = {"name": locked.name, "unit": locked.unit, "reorder_level": str(locked.reorder_level)}
    locked.name = name[:200]
    locked.unit = unit
    locked.reorder_level = reorder
    locked.save(update_fields=["name", "unit", "reorder_level"])
    log_action(
        action="warehouse.sku.update",
        actor=actor,
        entity=locked,
        old_values=old,
        new_values={"name": locked.name, "unit": locked.unit, "reorder_level": str(locked.reorder_level)},
    )
    return locked


@transaction.atomic
def adjust_stock(
    *,
    sku,
    warehouse,
    new_quantity,
    reason: str,
    actor=None,
    bin=None,
) -> StockMovement:
    """Set absolute on-hand quantity via ADJUSTMENT movement. Reason is mandatory."""
    from apps.warehouse.access import can_mutate_warehouse

    if not can_mutate_warehouse(actor):
        raise DomainError("Stok düzəlişi icazəniz yoxdur.")
    reason = (reason or "").strip()
    if not reason:
        raise DomainError("Düzəliş səbəbi tələb olunur.")
    qty = _as_decimal(new_quantity, field_label="Yeni miqdar")
    if qty < 0:
        raise DomainError("Stok miqdarı mənfi ola bilməz.")
    if not isinstance(sku, SKU):
        sku = SKU.objects.get(pk=sku)
    if not isinstance(warehouse, Warehouse):
        warehouse = Warehouse.objects.get(pk=warehouse)
    try:
        movement = apply_movement(
            sku=sku,
            warehouse=warehouse,
            movement_type=StockMovementType.ADJUSTMENT,
            quantity=qty,
            bin=bin,
            reference=f"ADJ:{actor.pk if actor else 'system'}",
            notes=f"Adjustment by {getattr(actor, 'username', '?')}: {reason}"[:500],
        )
    except ValueError as exc:
        raise DomainError(str(exc)) from exc
    log_action(
        action="warehouse.stock.adjust",
        actor=actor,
        entity=sku,
        new_values={
            "warehouse": warehouse.code,
            "quantity": str(qty),
            "reason": reason[:255],
            "movement_id": movement.pk,
        },
    )
    return movement


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
    from apps.maintenance.models import WorkOrderStatus

    qty = Decimal(quantity)
    if qty <= 0:
        raise DomainError("Miqdar sıfırdan böyük olmalıdır.")
    if work_order.status in {WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED}:
        raise DomainError("Tamamlanmış və ya ləğv edilmiş iş sifarişinə material çıxarıla bilməz.")
    issue = (
        WarehouseIssue.objects.select_for_update()
        .filter(work_order=work_order, warehouse=warehouse, status=IssueStatus.OPEN)
        .first()
    )
    created = issue is None
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
    apply_movement(
        sku=sku,
        warehouse=warehouse,
        movement_type=StockMovementType.RESERVATION,
        quantity=qty,
        reference=issue.code,
        work_order=work_order,
        notes="WO material reserve",
    )
    log_action(
        action="warehouse.issue.request",
        actor=actor,
        entity=issue,
        new_values={
            "code": issue.code,
            "work_order_id": work_order.pk,
            "sku_id": sku.pk,
            "qty": str(qty),
            "created": created,
        },
        source="warehouse",
    )
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
        unused_reserve = (line.requested_qty or Decimal("0")) - issued
        if unused_reserve > 0:
            apply_movement(
                sku=line.sku,
                warehouse=locked.warehouse,
                movement_type=StockMovementType.RELEASE,
                quantity=unused_reserve,
                reference=locked.code,
                work_order=locked.work_order,
                notes="unused reservation release",
            )
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
    log_action(
        action="warehouse.issue.confirm",
        actor=actor,
        entity=locked,
        new_values={
            "code": locked.code,
            "work_order_id": locked.work_order_id,
            "warehouse_id": locked.warehouse_id,
            "status": locked.status,
        },
        source="warehouse",
    )
    # Notify WO assignee (or requester) — material left the shelf for this WO.
    from apps.comms.services import notify_in_app

    recipient = None
    wo = locked.work_order
    if wo is not None and getattr(wo, "assigned_to_id", None):
        recipient = wo.assigned_to
    elif locked.requested_by_id:
        recipient = locked.requested_by
    if recipient is not None and getattr(recipient, "is_active", False):
        notify_in_app(
            user=recipient,
            message=f"Material WO-ya verildi: {locked.code}",
            ticket=getattr(wo, "ticket", None) if wo is not None else None,
            event_key=f"warehouse.issue.confirm.{locked.pk}",
        )
    return locked
