"""Procurement thin workflow: PR → approve → PO → receive → warehouse (Phase 9)."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core import events as bus
from apps.core.services import Service
from apps.procurement.models import (
    POLine,
    POStatus,
    PRLine,
    PRSource,
    PRStatus,
    PurchaseApprovalLimit,
    PurchaseOrder,
    PurchaseRequest,
    RFQ,
    RFQQuote,
)
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
    def _open_low_stock_pr_for_sku(cls, sku):
        return (
            PurchaseRequest.objects.filter(
                source=PRSource.LOW_STOCK,
                status__in={PRStatus.DRAFT, PRStatus.SUBMITTED, PRStatus.APPROVED},
                lines__sku=sku,
            )
            .distinct()
            .first()
        )

    @classmethod
    @transaction.atomic
    def create_pr_from_low_stock(cls, *, stock, requested_by=None, qty=None) -> PurchaseRequest:
        sku = stock.sku
        existing = cls._open_low_stock_pr_for_sku(sku)
        if existing is not None:
            return existing
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
    def create_pr_for_work_order(cls, wo, *, actor, description, qty) -> PurchaseRequest:
        text = (description or "").strip()
        cls.require(text, "Satınalma təsviri boş ola bilməz.")
        amount = Decimal(str(qty or "1"))
        cls.require(amount > 0, "Miqdar sıfırdan böyük olmalıdır.")
        pr = PurchaseRequest.objects.create(
            code=_next_code("PR", PurchaseRequest),
            title=f"{wo.code}: {text}"[:200],
            status=PRStatus.SUBMITTED,
            requested_by=actor,
            source=PRSource.WO,
            work_order=wo,
        )
        PRLine.objects.create(
            pr=pr,
            description=text[:255],
            qty=amount,
            unit="pcs",
        )
        return pr

    @classmethod
    def pr_estimated_amount(cls, pr: PurchaseRequest) -> Decimal:
        """Rough total for limit checks (qty only when no prices yet)."""
        total = Decimal("0")
        for line in pr.lines.all():
            total += Decimal(str(line.qty or 0))
        return total

    @classmethod
    def actor_within_approval_limit(cls, actor, amount: Decimal) -> bool:
        from apps.accounts.models import Role

        role = getattr(actor, "role", None) if actor else None
        if role in {Role.ADMIN, Role.MANAGEMENT}:
            return True
        if not role:
            return False
        limit = PurchaseApprovalLimit.objects.filter(role=role, is_active=True).first()
        if limit is None:
            return role in {Role.PROPERTY_FM, Role.SERVICE_DESK}
        return Decimal(str(amount)) <= Decimal(str(limit.max_amount))

    @classmethod
    @transaction.atomic
    def approve_pr(cls, pr: PurchaseRequest, *, actor=None) -> PurchaseRequest:
        cls.require(pr.status in {PRStatus.DRAFT, PRStatus.SUBMITTED}, "PR təsdiq üçün uyğun deyil.")
        amount = cls.pr_estimated_amount(pr)
        cls.require(
            cls.actor_within_approval_limit(actor, amount),
            "Satınalma limiti aşılır — Management/Admin təsdiqi lazımdır.",
        )
        req = ApprovalService.request(workflow_code="procurement.pr", requested_by=actor, entity=pr)
        ApprovalService.decide(req, approved=True, decided_by=actor, comment="PR approved")
        pr.status = PRStatus.APPROVED
        pr.save(update_fields=["status"])
        bus.emit(bus.PURCHASE_APPROVED, payload={"pr_id": pr.pk, "code": pr.code}, actor=actor)
        return pr

    @classmethod
    @transaction.atomic
    def create_rfq_from_pr(cls, pr: PurchaseRequest, *, title="") -> RFQ:
        cls.require(pr.status in {PRStatus.APPROVED, PRStatus.SUBMITTED}, "RFQ üçün PR uyğun deyil.")
        return RFQ.objects.create(
            code=_next_code("RFQ", RFQ),
            title=(title or pr.title)[:200],
            pr=pr,
        )

    @classmethod
    @transaction.atomic
    def add_rfq_quote(cls, rfq: RFQ, *, supplier_party, unit_price, lead_time_days=0, notes="") -> RFQQuote:
        return RFQQuote.objects.create(
            rfq=rfq,
            supplier_party=supplier_party,
            unit_price=Decimal(str(unit_price or 0)),
            lead_time_days=int(lead_time_days or 0),
            notes=notes or "",
        )

    @classmethod
    @transaction.atomic
    def select_rfq_quote_and_create_po(cls, quote: RFQQuote) -> PurchaseOrder:
        rfq = quote.rfq
        cls.require(rfq.pr_id, "RFQ Purchase Request-ə bağlı deyil.")
        pr = rfq.pr
        cls.require(pr.status == PRStatus.APPROVED, "Yalnız təsdiqlənmiş PR-dən PO.")
        RFQQuote.objects.filter(rfq=rfq, is_selected=True).update(is_selected=False)
        quote.is_selected = True
        quote.save(update_fields=["is_selected"])
        po = cls.create_po_from_pr(pr, supplier_party=quote.supplier_party)
        for line in po.lines.all():
            line.unit_price = quote.unit_price
            line.save(update_fields=["unit_price"])
        return po

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
            )
        pr.status = PRStatus.ORDERED
        pr.save(update_fields=["status"])
        return po

    @classmethod
    @transaction.atomic
    def receive_po(cls, po: PurchaseOrder, *, warehouse, actor=None, line_qtys=None) -> PurchaseOrder:
        """Receive PO into warehouse. ``line_qtys`` = {po_line_id: qty} for partial receive."""
        cls.require(po.status in {POStatus.SENT, POStatus.PARTIAL, POStatus.DRAFT}, "PO qəbul üçün uyğun deyil.")
        line_qtys = line_qtys or {}
        for line in po.lines.select_related("sku"):
            if not line.sku_id:
                continue
            remaining = (line.qty or Decimal("0")) - (line.received_qty or Decimal("0"))
            if remaining <= 0:
                continue
            if line.pk in line_qtys:
                take = Decimal(str(line_qtys[line.pk]))
            elif line_qtys:
                continue  # explicit map provided — skip unspecified lines
            else:
                take = remaining
            if take <= 0:
                continue
            if take > remaining:
                raise ValueError("Qəbul miqdarı qalan miqdardan çox ola bilməz.")
            apply_movement(
                sku=line.sku,
                warehouse=warehouse,
                movement_type=StockMovementType.RECEIPT,
                quantity=take,
                reference=po.code,
            )
            line.received_qty = (line.received_qty or Decimal("0")) + take
            line.save(update_fields=["received_qty"])
        incomplete = any(
            (ln.received_qty or 0) < (ln.qty or 0) for ln in po.lines.all() if ln.sku_id
        )
        po.status = POStatus.PARTIAL if incomplete else POStatus.RECEIVED
        po.save(update_fields=["status"])
        if po.pr_id and po.pr.work_order_id:
            from apps.maintenance.costs import sync_procurement_cost

            sync_procurement_cost(po.pr.work_order)
        bus.emit(bus.PO_RECEIVED, payload={"po_id": po.pk, "code": po.code}, actor=actor)
        return po
