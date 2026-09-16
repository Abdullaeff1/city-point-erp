from decimal import Decimal

from django.db import transaction

from apps.warehouse.models import Stock, StockMovement, StockMovementType


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
        stock.quantity = (stock.quantity or Decimal("0")) + (sign * qty)
    stock.save(update_fields=["quantity"])
    return movement
