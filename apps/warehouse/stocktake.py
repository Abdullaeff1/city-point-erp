"""Warehouse stocktake / physical count (Product Delivery Phase 8).

Timing policy (no warehouse-wide freeze):
- baseline_qty: on-hand at session start (evidence).
- expected_qty: on-hand locked when the operator saves the physical count for that line.
  Case A (issue before count): expected reflects the issue → variance can be zero.
- Posting applies the signed variance as a delta against *current* on-hand
  (new = current + variance), so Case B receipts after count are preserved.
- Matching counts create no movement. Uncounted lines never become shortages.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import log_action
from apps.core.services import DomainError
from apps.warehouse.access import can_count_stocktake, can_post_stocktake_adjustments
from apps.warehouse.models import (
    SKU,
    Stock,
    StockMovement,
    StockMovementType,
    Stocktake,
    StocktakeLine,
    StocktakeStatus,
    Warehouse,
)
from apps.warehouse.services import adjust_stock, _as_decimal


BALANCE_MOVEMENT_TYPES = (
    StockMovementType.RECEIPT,
    StockMovementType.ISSUE,
    StockMovementType.RETURN,
    StockMovementType.TRANSFER,
    StockMovementType.ADJUSTMENT,
)


def _next_stocktake_code() -> str:
    codes = Stocktake.objects.filter(code__startswith="ST-").values_list("code", flat=True)
    numbers = []
    for code in codes:
        try:
            numbers.append(int(str(code).split("-")[1]))
        except (IndexError, ValueError):
            continue
    nxt = (max(numbers) + 1) if numbers else 1001
    return f"ST-{nxt}"


def _on_hand_for(*, sku, warehouse, bin=None) -> Decimal:
    try:
        stock = Stock.objects.get(sku=sku, warehouse=warehouse, bin=bin)
    except Stock.DoesNotExist:
        return Decimal("0")
    return stock.quantity or Decimal("0")


def stocktake_progress(stocktake: Stocktake) -> dict:
    lines = list(stocktake.lines.all())
    total = len(lines)
    counted = sum(1 for ln in lines if ln.counted_qty is not None)
    outstanding = total - counted
    diffs = sum(
        1
        for ln in lines
        if ln.counted_qty is not None and ln.variance_qty is not None and ln.variance_qty != 0
    )
    shortages = sum(
        1 for ln in lines if ln.counted_qty is not None and (ln.variance_qty or 0) < 0
    )
    surpluses = sum(
        1 for ln in lines if ln.counted_qty is not None and (ln.variance_qty or 0) > 0
    )
    recounts = sum(1 for ln in lines if ln.recount_required)
    return {
        "total_lines": total,
        "counted_lines": counted,
        "outstanding_lines": outstanding,
        "difference_lines": diffs,
        "shortage_lines": shortages,
        "surplus_lines": surpluses,
        "recount_lines": recounts,
    }


def refresh_activity_flags(stocktake: Stocktake) -> int:
    """Flag counted lines that saw balance movements after counted_at."""
    flagged = 0
    for line in stocktake.lines.filter(counted_qty__isnull=False, counted_at__isnull=False):
        qs = StockMovement.objects.filter(
            sku=line.sku,
            warehouse=stocktake.warehouse,
            movement_type__in=BALANCE_MOVEMENT_TYPES,
            created_at__gt=line.counted_at,
        )
        if line.adjustment_movement_id:
            qs = qs.exclude(pk=line.adjustment_movement_id)
        has_activity = qs.exists()
        if has_activity != line.activity_after_count:
            line.activity_after_count = has_activity
            # Visible flag only — known post-count movements use delta posting (Case B).
            # Operators mark recount_required when timing of the physical count is unclear.
            line.save(update_fields=["activity_after_count"])
            if has_activity:
                flagged += 1
    return flagged


@transaction.atomic
def start_stocktake(*, warehouse, actor, notes: str = "") -> Stocktake:
    if not can_count_stocktake(actor):
        raise DomainError("İnventar sayımı başlatmaq icazəniz yoxdur.")
    if not isinstance(warehouse, Warehouse):
        warehouse = Warehouse.objects.get(pk=warehouse)
    open_exists = Stocktake.objects.filter(
        warehouse=warehouse,
        status__in=[StocktakeStatus.OPEN, StocktakeStatus.POSTING],
    ).exists()
    if open_exists:
        raise DomainError("Bu anbarda artıq açıq inventar sayımı var.")

    now = timezone.now()
    stocktake = Stocktake.objects.create(
        code=_next_stocktake_code(),
        warehouse=warehouse,
        status=StocktakeStatus.OPEN,
        started_by=actor,
        started_at=now,
        notes=(notes or "").strip()[:2000],
    )
    stocks = (
        Stock.objects.filter(warehouse=warehouse)
        .select_related("sku", "bin")
        .order_by("sku__code")
    )
    lines = []
    for stock in stocks:
        lines.append(
            StocktakeLine(
                stocktake=stocktake,
                sku=stock.sku,
                bin=stock.bin,
                unit=stock.sku.unit or "pcs",
                baseline_qty=stock.quantity or Decimal("0"),
                baseline_at=now,
            )
        )
    if lines:
        StocktakeLine.objects.bulk_create(lines)
    log_action(
        action="warehouse.stocktake.start",
        actor=actor,
        entity=stocktake,
        new_values={
            "code": stocktake.code,
            "warehouse": warehouse.code,
            "lines": len(lines),
        },
    )
    return stocktake


@transaction.atomic
def add_found_sku(*, stocktake: Stocktake, sku, actor, bin=None) -> StocktakeLine:
    """Include a catalog SKU found physically with no recorded balance in this warehouse."""
    if not can_count_stocktake(actor):
        raise DomainError("Sayım sətri əlavə etmək icazəniz yoxdur.")
    locked = Stocktake.objects.select_for_update().get(pk=stocktake.pk)
    if locked.status != StocktakeStatus.OPEN:
        raise DomainError("Yalnız açıq sayımlara SKU əlavə edilə bilər.")
    if not isinstance(sku, SKU):
        sku = SKU.objects.get(pk=sku)
    if StocktakeLine.objects.filter(stocktake=locked, sku=sku, bin=bin).exists():
        raise DomainError("Bu SKU artıq sayımda var.")
    now = timezone.now()
    on_hand = _on_hand_for(sku=sku, warehouse=locked.warehouse, bin=bin)
    line = StocktakeLine.objects.create(
        stocktake=locked,
        sku=sku,
        bin=bin,
        unit=sku.unit or "pcs",
        baseline_qty=on_hand,
        baseline_at=now,
    )
    log_action(
        action="warehouse.stocktake.add_sku",
        actor=actor,
        entity=locked,
        new_values={"sku": sku.code, "baseline": str(on_hand)},
    )
    return line


def save_line_count(
    *,
    line: StocktakeLine,
    counted_raw,
    actor,
    displayed_on_hand=None,
    force_recount: bool = False,
) -> StocktakeLine:
    """Save physical quantity. Empty raw must not become zero (caller skips empty).

    Timing:
    - expected_qty is captured at successful save (system on-hand then).
    - displayed_on_hand is the on-hand shown when the form was rendered. If stock
      moved before save (Case A), reject the stale observation and require recount
      — do not create a postable false surplus/shortage.
    - Resubmitting an already-saved count without an explicit recount preserves
      the original expected_qty (Case B).
    - Deliberate recount: mark_line_recount / clear_line_count / force_recount
      then save establishes a new comparison point (Case C).
    """
    if not can_count_stocktake(actor):
        raise DomainError("Sayım daxil etmək icazəniz yoxdur.")

    stale_message = None
    with transaction.atomic():
        locked_st = Stocktake.objects.select_for_update().get(pk=line.stocktake_id)
        if locked_st.status != StocktakeStatus.OPEN:
            raise DomainError("Bu sayım artıq bağlıdır.")
        locked = StocktakeLine.objects.select_for_update().get(pk=line.pk)
        sku = SKU.objects.get(pk=locked.sku_id)

        text = str(counted_raw if counted_raw is not None else "").strip()
        if text == "":
            raise DomainError("Boş sahə sıfır kimi qəbul edilmir; sətir sayılmamış qalır.")
        qty = _as_decimal(text, field_label="Sayılan miqdar")
        if qty < 0:
            raise DomainError("Sayılan miqdar mənfi ola bilməz.")

        already = locked.counted_qty is not None
        allow_fresh = force_recount or locked.recount_required or not already
        if already and not allow_fresh:
            if qty == locked.counted_qty:
                # Idempotent form resubmit — keep original expected / variance.
                return locked
            raise DomainError(
                f"{sku.code}: mövcud sayımı dəyişmək üçün əvvəlcə «Yenidən say» "
                "işarələyin və ya sətri təmizləyin."
            )

        now = timezone.now()
        expected = _on_hand_for(sku=sku, warehouse=locked_st.warehouse, bin=locked.bin_id)

        if displayed_on_hand is not None and str(displayed_on_hand).strip() != "":
            snap = _as_decimal(displayed_on_hand, field_label="Göstərilən qalıq")
            if snap != expected:
                locked.recount_required = True
                locked.save(update_fields=["recount_required"])
                log_action(
                    action="warehouse.stocktake.stale_observation",
                    actor=actor,
                    entity=locked_st,
                    new_values={
                        "sku": sku.code,
                        "displayed": str(snap),
                        "current": str(expected),
                        "rejected_count": str(qty),
                    },
                )
                # Commit recount flag, then raise outside this block.
                stale_message = (
                    f"{sku.code}: stok forma açılandan sonra dəyişib "
                    f"({snap} → {expected}). Köhnə müşahidə saxlanılmadı — yenidən sayın."
                )
                locked = locked
            else:
                snap = None
        else:
            snap = None

        if stale_message is None:
            variance = qty - expected
            locked.expected_qty = expected
            locked.counted_qty = qty
            locked.variance_qty = variance
            locked.counted_at = now
            locked.counted_by = actor
            locked.recount_required = False
            locked.activity_after_count = False
            locked.save(
                update_fields=[
                    "expected_qty",
                    "counted_qty",
                    "variance_qty",
                    "counted_at",
                    "counted_by",
                    "recount_required",
                    "activity_after_count",
                ]
            )
            log_action(
                action="warehouse.stocktake.count_line",
                actor=actor,
                entity=locked_st,
                new_values={
                    "sku": sku.code,
                    "expected": str(expected),
                    "counted": str(qty),
                    "variance": str(variance),
                    "recount": bool(already and allow_fresh),
                },
            )

    if stale_message:
        raise DomainError(stale_message)
    return locked


@transaction.atomic
def clear_line_count(*, line: StocktakeLine, actor) -> StocktakeLine:
    if not can_count_stocktake(actor):
        raise DomainError("Sayımı silmək icazəniz yoxdur.")
    locked_st = Stocktake.objects.select_for_update().get(pk=line.stocktake_id)
    if locked_st.status != StocktakeStatus.OPEN:
        raise DomainError("Bu sayım artıq bağlıdır.")
    locked = StocktakeLine.objects.select_for_update().get(pk=line.pk)
    locked.expected_qty = None
    locked.counted_qty = None
    locked.variance_qty = None
    locked.counted_at = None
    locked.counted_by = None
    locked.recount_required = False
    locked.activity_after_count = False
    locked.save(
        update_fields=[
            "expected_qty",
            "counted_qty",
            "variance_qty",
            "counted_at",
            "counted_by",
            "recount_required",
            "activity_after_count",
        ]
    )
    return locked


@transaction.atomic
def mark_line_recount(*, line: StocktakeLine, actor, required: bool = True) -> StocktakeLine:
    """Identifiable recount action. On an open count, clears the prior observation
    so the next save establishes a new expected comparison point."""
    if not can_count_stocktake(actor):
        raise DomainError("Yenidən sayım işarəsi üçün icazə yoxdur.")
    locked_st = Stocktake.objects.select_for_update().get(pk=line.stocktake_id)
    if locked_st.status not in (StocktakeStatus.OPEN, StocktakeStatus.COMPLETED):
        raise DomainError("Bu statusda yenidən sayım işarələnə bilməz.")
    locked = StocktakeLine.objects.select_for_update().get(pk=line.pk)
    locked.recount_required = bool(required)
    update_fields = ["recount_required"]
    if required and locked_st.status == StocktakeStatus.OPEN:
        locked.expected_qty = None
        locked.counted_qty = None
        locked.variance_qty = None
        locked.counted_at = None
        locked.counted_by = None
        locked.activity_after_count = False
        update_fields.extend(
            [
                "expected_qty",
                "counted_qty",
                "variance_qty",
                "counted_at",
                "counted_by",
                "activity_after_count",
            ]
        )
    locked.save(update_fields=update_fields)
    log_action(
        action="warehouse.stocktake.mark_recount",
        actor=actor,
        entity=locked_st,
        new_values={"line_id": locked.pk, "required": bool(required)},
    )
    return locked


@transaction.atomic
def complete_stocktake(*, stocktake: Stocktake, actor) -> Stocktake:
    """Finish counting. Uncounted lines stay uncounted — no implied shortages."""
    if not can_count_stocktake(actor):
        raise DomainError("Sayımı bitirmək icazəniz yoxdur.")
    locked = Stocktake.objects.select_for_update().get(pk=stocktake.pk)
    if locked.status != StocktakeStatus.OPEN:
        raise DomainError("Yalnız açıq sayım bitirilə bilər.")
    refresh_activity_flags(locked)
    locked.status = StocktakeStatus.COMPLETED
    locked.completed_by = actor
    locked.completed_at = timezone.now()
    locked.save(update_fields=["status", "completed_by", "completed_at"])
    progress = stocktake_progress(locked)
    log_action(
        action="warehouse.stocktake.complete",
        actor=actor,
        entity=locked,
        new_values=progress,
    )
    return locked


@transaction.atomic
def post_stocktake_variances(*, stocktake: Stocktake, actor, reason: str = "") -> Stocktake:
    """
    Post approved differences via adjust_stock delta:
    new_on_hand = current_on_hand + (counted - expected_at_count).
    Idempotent under concurrent/retry: status gate + per-line movement link.
    """
    if not can_post_stocktake_adjustments(actor):
        raise DomainError("Stok düzəlişi icazəniz yoxdur.")

    locked = Stocktake.objects.select_for_update().get(pk=stocktake.pk)
    if locked.status == StocktakeStatus.POSTED:
        return locked
    if locked.status == StocktakeStatus.POSTING:
        raise DomainError("Düzəlişlər artıq tətbiq olunur; bir az gözləyin.")
    if locked.status != StocktakeStatus.COMPLETED:
        raise DomainError("Yalnız bitmiş sayım üzrə fərqlər tətbiq edilə bilər.")

    reason = (reason or "").strip() or f"Stocktake {locked.code}"
    refresh_activity_flags(locked)

    locked.status = StocktakeStatus.POSTING
    locked.save(update_fields=["status"])

    now = timezone.now()
    posted_count = 0
    # Avoid select_related under select_for_update (PG rejects nullable outer joins).
    lines = list(
        StocktakeLine.objects.select_for_update().filter(stocktake=locked).order_by("pk")
    )
    for line in lines:
        if line.counted_qty is None:
            continue
        if line.variance_qty is None or line.variance_qty == 0:
            continue
        if line.adjustment_movement_id:
            continue
        if line.recount_required:
            raise DomainError(
                f"{line.sku_id}: yenidən sayım tələb olunur; fərq tətbiq edilmədi."
            )

        sku = SKU.objects.get(pk=line.sku_id)
        current = _on_hand_for(sku=sku, warehouse=locked.warehouse, bin=line.bin_id)
        new_qty = current + line.variance_qty
        if new_qty < 0:
            raise DomainError(
                f"{sku.code}: düzəlişdən sonra stok mənfi olardı ({new_qty})."
            )
        movement = adjust_stock(
            sku=sku,
            warehouse=locked.warehouse,
            new_quantity=new_qty,
            reason=f"{reason} [{locked.code}:{sku.code} var={line.variance_qty}]",
            actor=actor,
            bin=line.bin_id,
        )
        # Strengthen movement reference for audit trail.
        StockMovement.objects.filter(pk=movement.pk).update(
            reference=f"ST:{locked.code}:{sku.code}",
            notes=(
                f"Stocktake {locked.code} variance {line.variance_qty} "
                f"(counted {line.counted_qty} vs expected {line.expected_qty})"
            )[:500],
        )
        line.adjustment_movement_id = movement.pk
        line.posted_at = now
        line.save(update_fields=["adjustment_movement", "posted_at"])
        posted_count += 1

    locked.status = StocktakeStatus.POSTED
    locked.posted_by = actor
    locked.posted_at = now
    locked.save(update_fields=["status", "posted_by", "posted_at"])
    log_action(
        action="warehouse.stocktake.post",
        actor=actor,
        entity=locked,
        new_values={"code": locked.code, "posted_lines": posted_count},
    )
    return locked


def parse_count_fields(post_data) -> list[tuple[int, str, str | None]]:
    """Extract (line_id, raw_value, displayed_on_hand) pairs; omit empty counts."""
    pairs = []
    for key, raw in post_data.items():
        if not key.startswith("count_"):
            continue
        try:
            line_id = int(key.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        text = str(raw if raw is not None else "").strip()
        if text == "":
            continue
        snap_raw = post_data.get(f"snap_{line_id}")
        snap = str(snap_raw).strip() if snap_raw is not None and str(snap_raw).strip() != "" else None
        pairs.append((line_id, text, snap))
    return pairs
