from decimal import Decimal

from django.db import transaction

from apps.core.services import DomainError
from apps.maintenance.models import CostLineKind, CostLineSource, WorkOrderCostLine


def line_amount(qty, unit_price) -> Decimal:
    return (Decimal(qty) * Decimal(unit_price)).quantize(Decimal("0.01"))


def refresh_cost_totals(wo) -> None:
    material = Decimal("0")
    labor = Decimal("0")
    for line in wo.cost_lines.all():
        if not line.unit_price or line.unit_price <= 0:
            continue
        if line.kind == CostLineKind.MATERIAL:
            material += line.amount
        else:
            labor += line.amount
    wo.material_cost = material
    wo.labor_cost = labor
    wo.save(update_fields=["material_cost", "labor_cost"])


def sync_procurement_cost(wo) -> None:
    """Mirror priced purchase-order lines onto the work-order material sheet."""
    from apps.procurement.models import POLine

    lines = POLine.objects.filter(po__pr__work_order=wo).select_related("po")
    seen = []
    for line in lines:
        if not line.unit_price or line.unit_price <= 0:
            WorkOrderCostLine.objects.filter(po_line=line).delete()
            continue
        qty = line.received_qty if line.received_qty and line.received_qty > 0 else line.qty
        cost, _ = WorkOrderCostLine.objects.update_or_create(
            po_line=line,
            defaults={
                "work_order": wo,
                "kind": CostLineKind.MATERIAL,
                "source": CostLineSource.PROCUREMENT,
                "description": line.description[:255],
                "qty": qty,
                "unit": "ədəd",
                "unit_price": line.unit_price,
                "amount": line_amount(qty, line.unit_price),
            },
        )
        seen.append(cost.pk)
    WorkOrderCostLine.objects.filter(
        work_order=wo,
        source=CostLineSource.PROCUREMENT,
    ).exclude(pk__in=seen).delete()
    refresh_cost_totals(wo)


@transaction.atomic
def save_cost_sheet(wo, *, material_rows, labor_rows, resident_amount, billable) -> None:
    _apply_rows(wo, CostLineKind.MATERIAL, material_rows)
    _apply_rows(wo, CostLineKind.LABOR, labor_rows)
    wo.billable = billable
    wo.resident_amount = resident_amount
    wo.save(update_fields=["billable", "resident_amount"])
    refresh_cost_totals(wo)


def _apply_rows(wo, kind, rows) -> None:
    seen = []
    for index, row in enumerate(rows):
        description = (row.get("description") or "").strip()
        line_id = row.get("id") or None
        if line_id:
            line = WorkOrderCostLine.objects.filter(pk=line_id, work_order=wo, kind=kind).first()
            if line is None:
                raise DomainError("Xərc sətri bu iş sifarişinə aid deyil.")
            if line.source == CostLineSource.MANUAL:
                if not description:
                    line.delete()
                    continue
                if row["qty"] <= 0:
                    raise DomainError("Miqdar sıfırdan böyük olmalıdır.")
                line.description = description[:255]
                line.qty = row["qty"]
                line.unit = (row.get("unit") or "ədəd")[:16]
            line.unit_price = row["unit_price"]
            line.amount = line_amount(line.qty, line.unit_price)
            line.sort_order = index
            line.save()
            _write_back_price(line)
            seen.append(line.pk)
            continue
        if not description:
            continue
        if row["qty"] <= 0:
            raise DomainError("Miqdar sıfırdan böyük olmalıdır.")
        created = WorkOrderCostLine.objects.create(
            work_order=wo,
            kind=kind,
            source=CostLineSource.MANUAL,
            description=description[:255],
            qty=row["qty"],
            unit=(row.get("unit") or "ədəd")[:16],
            unit_price=row["unit_price"],
            amount=line_amount(row["qty"], row["unit_price"]),
            sort_order=index,
        )
        seen.append(created.pk)
    WorkOrderCostLine.objects.filter(
        work_order=wo,
        kind=kind,
        source=CostLineSource.MANUAL,
    ).exclude(pk__in=seen).delete()


def _write_back_price(line) -> None:
    if line.source == CostLineSource.WAREHOUSE and line.warehouse_issue_line_id:
        issue_line = line.warehouse_issue_line
        issue_line.unit_cost = line.unit_price
        issue_line.save(update_fields=["unit_cost"])
    elif line.source == CostLineSource.PROCUREMENT and line.po_line_id:
        po_line = line.po_line
        po_line.unit_price = line.unit_price
        po_line.save(update_fields=["unit_price"])
