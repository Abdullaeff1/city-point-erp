"""Procurement thin workflow: PR → approve → PO → receive → warehouse (Phase 9)."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core import events as bus
from apps.core.services import Service
from apps.procurement.models import POLine, POStatus, PRLine, PRSource, PRStatus, PurchaseOrder, PurchaseRequest
from apps.warehouse.models import StockMovementType
from apps.warehouse.services import apply_movement
from apps.workflows.services import ApprovalService


def _next_code(prefix: str, model, field="code") -> str:
    codes = model.objects.filter(**{f"{field}__startswith": f"{prefix}-"}).values_list(field, flat=True)
    numbers = []
    for code in codes:
        try:
            numbers.append(int(str(code).split("-")[1]))
        except (IndexError, ValueError):
            continue
    nxt = (max(numbers) + 1) if numbers else 1001
    return f"{prefix}-{nxt}"


class ProcurementService(Service):
    @classmethod
    @transaction.atomic
    def create_pr_from_low_stock(cls, *, stock, requested_by=None, qty=None) -> PurchaseRequest:
        sku = stock.sku
        need = qty if qty is not None else max((sku.reorder_level or 0) - (stock.quantity or 0), 1)
        pr = PurchaseRequest.objects.create(
            code=_next_code("PR", PurchaseRequest),
            title=f"Low stock: {sku.code}",
            status=PRStatus.SUBMITTED,
            requested_by=requested_by,
            source=PRSource.LOW_STOCK,
        )
        PRLine.objects.create(
            pr=pr,
            sku=sku,
            description=sku.name or sku.code,
            qty=Decimal(str(need)),
            unit=getattr(sku, "unit", None) or "pcs",
        )
        return pr

    @classmethod
    @transaction.atomic
    def approve_pr(cls, pr: PurchaseRequest, *, actor=None) -> PurchaseRequest:
        cls.require(pr.status in {PRStatus.DRAFT, PRStatus.SUBMITTED}, "PR təsdiq üçün uyğun deyil.")
        req = ApprovalService.request(workflow_code="procurement.pr", requested_by=actor, entity=pr)
        ApprovalService.decide(req, approved=True, decided_by=actor, comment="PR approved")
        pr.status = PRStatus.APPROVED
        pr.save(update_fields=["status"])
        bus.emit(bus.PURCHASE_APPROVED, payload={"pr_id": pr.pk, "code": pr.code}, actor=actor)
        return pr

    @classmethod
    @transaction.atomic
    def create_po_from_pr(cls, pr: PurchaseRequest, *, supplier_party=None) -> PurchaseOrder:
        cls.require(pr.status == PRStatus.APPROVED, "Yalnız təsdiqlənmiş PR-dən PO.")
        po = PurchaseOrder.objects.create(
            code=_next_code("PO", PurchaseOrder),
            supplier_party=supplier_party,
            status=POStatus.SENT,
            pr=pr,
            ordered_at=timezone.localdate(),
        )
        for line in pr.lines.all():
            POLine.objects.create(
                po=po,
                description=line.description,
                sku=line.sku,
                qty=line.qty,
                unit=line.unit,
            )
        pr.status = PRStatus.ORDERED
        pr.save(update_fields=["status"])
        return po

    @classmethod
    @transaction.atomic
    def receive_po(cls, po: PurchaseOrder, *, warehouse, actor=None) -> PurchaseOrder:
        cls.require(po.status in {POStatus.SENT, POStatus.PARTIAL, POStatus.DRAFT}, "PO qəbul üçün uyğun deyil.")
        for line in po.lines.select_related("sku"):
            if not line.sku_id:
                continue
            remaining = (line.qty or 0) - (line.received_qty or 0)
            if remaining <= 0:
                continue
            apply_movement(
                sku=line.sku,
                warehouse=warehouse,
                movement_type=StockMovementType.RECEIPT,
                quantity=remaining,
                reference=po.code,
            )
            line.received_qty = line.qty
            line.save(update_fields=["received_qty"])
        po.status = POStatus.RECEIVED
        po.save(update_fields=["status"])
        bus.emit(bus.PO_RECEIVED, payload={"po_id": po.pk, "code": po.code}, actor=actor)
        return po
