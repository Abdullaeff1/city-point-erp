"""Procurement thin workflow: PR → approve → PO → receive → warehouse (Phase 9)."""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import events as bus
from apps.core.services import DomainError, Service
from django.contrib.contenttypes.models import ContentType

from apps.procurement.models import (
    GoodsReceiptOperation,
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
from apps.workflows.models import ApprovalRequest, ApprovalStatus
from apps.workflows.services import ApprovalService

_QTY_QUANT = Decimal("0.001")
_MONEY_QUANT = Decimal("0.01")
_SUPPORTED_CURRENCY = "AZN"
_INACTIVE_PO_STATUSES = {POStatus.CANCELLED}
_RECEIVABLE_PO_STATUSES = {POStatus.SENT, POStatus.PARTIAL, POStatus.DRAFT}

WF_PROCUREMENT_PR = "procurement.pr"
WF_PROCUREMENT_COMMITMENT = "procurement.commitment"

# Only these bases may authorize a spending ceiling. Quantity-era payloads lack them.
VERIFIED_MONETARY_BASES = frozenset(
    {
        "rfq_quote_unit_price_x_pr_qty",
        "priced_po_unit_price_x_pr_qty",
        "rfq_quote_lines_gross",
    }
)


def _quantize_money(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


class AmountAssessment:
    """Comparable monetary total for limit / escalation decisions."""

    __slots__ = ("amount", "currency", "reason", "basis")

    def __init__(
        self,
        amount: Decimal | None,
        currency: str = "",
        reason: str = "ok",
        basis: str = "",
    ):
        self.amount = amount
        self.currency = currency or ""
        self.reason = reason
        self.basis = basis

    @property
    def is_known(self) -> bool:
        return self.amount is not None and bool(self.currency)


def _quantize_qty(value) -> Decimal:
    try:
        qty = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, AttributeError, TypeError) as exc:
        raise DomainError("Miqdar düzgün rəqəm olmalıdır.") from exc
    if qty != qty.quantize(_QTY_QUANT):
        raise DomainError("Miqdar ən çox 3 onluq dəqiqliyə malik ola bilər.")
    return qty.quantize(_QTY_QUANT, rounding=ROUND_HALF_UP)


def _normalize_line_qtys(raw_line_qtys) -> dict[int, Decimal]:
    if not raw_line_qtys:
        return {}
    normalized: dict[int, Decimal] = {}
    for key, value in raw_line_qtys.items():
        try:
            line_id = int(key)
        except (TypeError, ValueError) as exc:
            raise DomainError("PO sətiri düzgün deyil.") from exc
        qty = _quantize_qty(value)
        if qty < 0:
            raise DomainError("Qəbul miqdarı mənfi ola bilməz.")
        if qty == 0:
            continue
        normalized[line_id] = qty
    return normalized


def _receipt_payload_fingerprint(
    *,
    po_id: int,
    warehouse_id: int,
    mode: str,
    line_qtys: dict[int, Decimal] | None,
) -> str:
    if mode == GoodsReceiptOperation.MODE_FULL:
        lines_payload: list | None = None
    else:
        lines_payload = [
            [int(line_id), format(qty, "f")]
            for line_id, qty in sorted((line_qtys or {}).items(), key=lambda item: item[0])
        ]
    blob = json.dumps(
        {
            "po_id": int(po_id),
            "warehouse_id": int(warehouse_id),
            "mode": mode,
            "lines": lines_payload,
        },
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _mark_receipt_replay(po: PurchaseOrder) -> PurchaseOrder:
    po.receipt_replayed = True
    return po


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
    def create_pr_for_work_order(cls, wo, *, actor, description, qty, sku=None) -> PurchaseRequest:
        text = (description or "").strip()
        if not text and sku is not None:
            text = (getattr(sku, "name", None) or getattr(sku, "code", None) or "SKU")[:255]
        cls.require(text, "Satınalma təsviri boş ola bilməz.")
        amount = Decimal(str(qty or "1"))
        cls.require(amount > 0, "Miqdar sıfırdan böyük olmalıdır.")
        unit = "pcs"
        if sku is not None:
            unit = (getattr(sku, "unit", None) or "pcs")[:16]
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
            sku=sku,
            description=text[:255],
            qty=amount,
            unit=unit,
        )
        return pr

    @classmethod
    def assert_can_edit_procurement(cls, actor) -> None:
        from apps.accounts.models import Role
        from apps.rbac.services import user_has_permission

        if not actor or not getattr(actor, "is_authenticated", False):
            raise DomainError("Satınalma redaktəsi icazəniz yoxdur.")
        if getattr(actor, "role", None) == Role.MANAGEMENT:
            raise DomainError("Rəhbərlik satınalmanı yalnız baxış / təsdiq hub ilə idarə edir.")
        if not user_has_permission(actor, "procurement.edit"):
            raise DomainError("Satınalma redaktəsi icazəniz yoxdur.")

    @classmethod
    @transaction.atomic
    def create_manual_pr(
        cls,
        *,
        actor,
        title: str,
        lines: list[dict],
        notes: str = "",
    ) -> PurchaseRequest:
        """Operator-created MANUAL PR. Source/requester assigned server-side only."""
        from apps.audit.services import log_action
        from apps.warehouse.models import SKU

        cls.assert_can_edit_procurement(actor)
        title = (title or "").strip()
        cls.require(title, "Başlıq tələb olunur.")
        cleaned: list[dict] = []
        for raw in lines or []:
            desc = (raw.get("description") or "").strip()
            if not desc and not raw.get("sku_id"):
                continue
            qty = Decimal(str(raw.get("qty") or "0"))
            cls.require(qty > 0, "Hər sətir üçün miqdar sıfırdan böyük olmalıdır.")
            sku = None
            sku_id = raw.get("sku_id") or None
            if sku_id:
                sku = SKU.objects.filter(pk=sku_id).first()
                if sku is None:
                    raise DomainError("SKU tapılmadı.")
                if not desc:
                    desc = sku.name or sku.code
            unit = ((raw.get("unit") or (sku.unit if sku else "pcs")) or "pcs")[:16]
            cleaned.append({"description": desc[:255], "qty": qty, "unit": unit, "sku": sku})
        cls.require(cleaned, "Ən azı bir sətir tələb olunur.")
        pr = PurchaseRequest.objects.create(
            code=_next_code("PR", PurchaseRequest),
            title=title[:200],
            status=PRStatus.SUBMITTED,
            requested_by=actor,
            source=PRSource.MANUAL,
            notes=(notes or "").strip(),
        )
        for row in cleaned:
            PRLine.objects.create(
                pr=pr,
                sku=row["sku"],
                description=row["description"],
                qty=row["qty"],
                unit=row["unit"],
            )
        log_action(
            action="procurement.pr.create_manual",
            actor=actor,
            entity=pr,
            new_values={"code": pr.code, "source": pr.source, "lines": len(cleaned)},
        )
        return pr

    @classmethod
    @transaction.atomic
    def create_or_update_supplier(
        cls,
        *,
        actor,
        legal_name: str,
        brand_name: str = "",
        tax_id: str = "",
        contact_email: str = "",
        contact_phone: str = "",
        notes: str = "",
        status: str = "",
        party=None,
    ):
        """Party + SUPPLIER role. Never creates ResidentCompany."""
        from apps.audit.services import log_action
        from apps.parties.models import Party, PartyRole, PartyRoleCode, PartyStatus, PartyType

        cls.assert_can_edit_procurement(actor)
        legal_name = (legal_name or "").strip()
        cls.require(legal_name, "Podratçı adı tələb olunur.")
        tax_id = (tax_id or "").strip()[:64]
        brand_name = (brand_name or "").strip()[:200]
        contact_email = (contact_email or "").strip()
        contact_phone = (contact_phone or "").strip()[:64]
        notes = (notes or "").strip()
        status = status or PartyStatus.ACTIVE
        if status not in {c.value for c in PartyStatus}:
            status = PartyStatus.ACTIVE

        qs = Party.objects.filter(roles__role=PartyRoleCode.SUPPLIER)
        if party is not None:
            qs = qs.exclude(pk=party.pk)
        if tax_id and qs.filter(tax_id__iexact=tax_id).exists():
            raise DomainError("Bu VÖEN ilə podratçı artıq mövcuddur.")
        if qs.filter(legal_name__iexact=legal_name).exists():
            raise DomainError("Bu adla podratçı artıq mövcuddur.")

        created = False
        if party is None:
            party = Party.objects.create(
                party_type=PartyType.ORGANIZATION,
                legal_name=legal_name[:200],
                brand_name=brand_name,
                tax_id=tax_id,
                contact_email=contact_email,
                contact_phone=contact_phone,
                notes=notes,
                status=status,
            )
            PartyRole.objects.get_or_create(
                party=party, role=PartyRoleCode.SUPPLIER, defaults={"is_primary": True}
            )
            created = True
            action = "procurement.supplier.create"
        else:
            party = Party.objects.select_for_update().get(pk=party.pk)
            PartyRole.objects.get_or_create(
                party=party, role=PartyRoleCode.SUPPLIER, defaults={"is_primary": True}
            )
            party.legal_name = legal_name[:200]
            party.brand_name = brand_name
            party.tax_id = tax_id
            party.contact_email = contact_email
            party.contact_phone = contact_phone
            party.notes = notes
            party.status = status
            party.save(
                update_fields=[
                    "legal_name",
                    "brand_name",
                    "tax_id",
                    "contact_email",
                    "contact_phone",
                    "notes",
                    "status",
                ]
            )
            action = "procurement.supplier.update"
        log_action(
            action=action,
            actor=actor,
            entity=party,
            new_values={"legal_name": party.legal_name, "tax_id": party.tax_id, "created": created},
        )
        return party

    @classmethod
    def supplier_queryset(cls):
        from apps.parties.models import Party, PartyRoleCode

        return (
            Party.objects.filter(roles__role=PartyRoleCode.SUPPLIER)
            .distinct()
            .order_by("legal_name")
        )

    @classmethod
    def assess_pr_approval_amount(cls, pr: PurchaseRequest) -> AmountAssessment:
        """Monetary total available at PR approval time.

        PRLine has no unit price. Never treat line quantities as AZN spending.
        A populated but unpriced request is amount_unknown.
        """
        lines = list(pr.lines.all())
        if not lines:
            return AmountAssessment(None, "", "empty_request", "no_lines")
        # Future: when an approved estimate field exists, sum qty * price here with
        # fail-closed behaviour if any line lacks a usable price.
        return AmountAssessment(
            None,
            "",
            "amount_unknown",
            "pr_line_has_no_price",
        )

    @classmethod
    def pr_estimated_amount(cls, pr: PurchaseRequest) -> Decimal | None:
        """Backward-compatible alias — monetary total or None (never qty)."""
        return cls.assess_pr_approval_amount(pr).amount

    @classmethod
    def _po_line_matches_pr_line(cls, pr_line: PRLine, po_line: POLine) -> bool:
        if pr_line.sku_id and po_line.sku_id:
            return pr_line.sku_id == po_line.sku_id
        return (pr_line.description or "").strip() == (po_line.description or "").strip()

    @classmethod
    def pr_line_ordered_qty(cls, pr_line: PRLine) -> Decimal:
        total = Decimal("0")
        for po in pr_line.pr.purchase_orders.exclude(status__in=_INACTIVE_PO_STATUSES):
            for pol in po.lines.all():
                if cls._po_line_matches_pr_line(pr_line, pol):
                    total += Decimal(str(pol.qty or 0))
        return total

    @classmethod
    def pr_line_received_qty(cls, pr_line: PRLine) -> Decimal:
        total = Decimal("0")
        for po in pr_line.pr.purchase_orders.exclude(status__in=_INACTIVE_PO_STATUSES):
            for pol in po.lines.all():
                if cls._po_line_matches_pr_line(pr_line, pol):
                    total += Decimal(str(pol.received_qty or 0))
        return total

    @classmethod
    def pr_line_remaining_qty(cls, pr_line: PRLine) -> Decimal:
        remaining = Decimal(str(pr_line.qty or 0)) - cls.pr_line_ordered_qty(pr_line)
        return remaining if remaining > 0 else Decimal("0")

    @classmethod
    def pr_qty_progress(cls, pr: PurchaseRequest) -> list[dict]:
        """Operator-visible requested / ordered / received / outstanding per PR line."""
        rows = []
        for line in pr.lines.select_related("sku").all():
            requested = Decimal(str(line.qty or 0))
            ordered = cls.pr_line_ordered_qty(line)
            received = cls.pr_line_received_qty(line)
            rows.append(
                {
                    "line": line,
                    "requested": requested,
                    "ordered": ordered,
                    "received": received,
                    "outstanding_order": max(requested - ordered, Decimal("0")),
                    "outstanding_receipt": max(ordered - received, Decimal("0")),
                }
            )
        return rows

    @classmethod
    def resolve_po_line_qtys(
        cls, pr: PurchaseRequest, line_qtys: dict | None = None
    ) -> dict[int, Decimal]:
        """Map PR line id → qty to order. Default = all remaining. Never exceed remaining."""
        resolved: dict[int, Decimal] = {}
        for line in pr.lines.all():
            remaining = cls.pr_line_remaining_qty(line)
            if line_qtys is None:
                take = remaining
            else:
                raw = line_qtys.get(line.pk, line_qtys.get(str(line.pk)))
                if raw is None or str(raw).strip() == "":
                    take = Decimal("0")
                else:
                    take = _quantize_qty(raw)
            if take < 0:
                raise DomainError("Sifariş miqdarı mənfi ola bilməz.")
            if take > remaining:
                raise DomainError(
                    f"{line.description}: qalan {remaining}, tələb olunan {take}. "
                    "Əlavə sifariş üçün yenilənmiş PR / təsdiq tələb olunur."
                )
            if take > 0:
                resolved[line.pk] = take
        if not resolved:
            raise DomainError(
                "PR üzrə sifariş ediləcək qalan miqdar yoxdur. "
                "Əlavə vahid üçün yenilənmiş sorğu tələb olunur."
            )
        return resolved

    @classmethod
    def assess_quote_amount(cls, quote: RFQQuote, pr: PurchaseRequest) -> AmountAssessment:
        """Legacy header quote: unit_price × remaining PR qtys.

        Line-priced quotes use quote_lines gross via LineSourcingService.
        """
        from apps.procurement.line_sourcing import quote_line_amounts
        from apps.procurement.models import QuoteLineResponseStatus

        line_prices = list(quote.lines.all()) if hasattr(quote, "lines") else []
        if line_prices:
            total = Decimal("0")
            any_quoted = False
            for ql in line_prices:
                if ql.response_status != QuoteLineResponseStatus.QUOTED:
                    continue
                any_quoted = True
                amounts = quote_line_amounts(ql)
                if amounts["tax_basis"] == "unknown" or amounts["gross"] is None:
                    return AmountAssessment(
                        None, "", "amount_unknown", "quote_line_tax_unknown"
                    )
                currency = (ql.currency or _SUPPORTED_CURRENCY).strip().upper()
                if currency != _SUPPORTED_CURRENCY:
                    return AmountAssessment(
                        None, currency, "currency_unsupported", "rfq_quote_line_currency"
                    )
                # Comparable total uses remaining PR qty × unit (not under-quoted qty)
                rem = cls.pr_line_remaining_qty(ql.pr_line)
                if rem <= 0:
                    continue
                unit = _quantize_money(Decimal(str(ql.unit_price or 0)))
                # Rebuild gross for remaining qty with same tax basis
                if ql.vat_rate is None:
                    return AmountAssessment(
                        None, "", "amount_unknown", "quote_line_tax_unknown"
                    )
                rate = Decimal(str(ql.vat_rate))
                raw = _quantize_money(rem * unit)
                if ql.price_includes_vat:
                    gross = raw
                else:
                    gross = _quantize_money(raw + raw * rate)
                total += gross
            if not any_quoted:
                return AmountAssessment(None, "", "empty_request", "no_quoted_lines")
            return AmountAssessment(
                _quantize_money(total),
                _SUPPORTED_CURRENCY,
                "ok",
                "rfq_quote_lines_gross",
            )

        lines = list(pr.lines.all())
        if not lines:
            return AmountAssessment(None, "", "empty_request", "no_lines")
        currency = (getattr(quote, "currency", None) or _SUPPORTED_CURRENCY).strip().upper()
        if currency != _SUPPORTED_CURRENCY:
            return AmountAssessment(
                None,
                currency,
                "currency_unsupported",
                "rfq_quote_currency",
            )
        raw_price = getattr(quote, "unit_price", None)
        if raw_price is None:
            return AmountAssessment(None, "", "amount_unknown", "quote_price_missing")
        price = _quantize_money(Decimal(str(raw_price)))
        total = Decimal("0")
        any_remaining = False
        for line in lines:
            qty = cls.pr_line_remaining_qty(line)
            if qty > 0:
                any_remaining = True
            total += qty * price
        if not any_remaining:
            return AmountAssessment(None, "", "empty_request", "no_remaining_qty")
        return AmountAssessment(
            _quantize_money(total),
            _SUPPORTED_CURRENCY,
            "ok",
            "rfq_quote_unit_price_x_pr_qty",
        )

    # --- Line-level sourcing facades ---

    @classmethod
    def invite_supplier_to_rfq(cls, *args, **kwargs):
        from apps.procurement.line_sourcing import LineSourcingService

        return LineSourcingService.invite_supplier_to_rfq(*args, **kwargs)

    @classmethod
    def add_rfq_quote_lines(cls, *args, **kwargs):
        from apps.procurement.line_sourcing import LineSourcingService

        return LineSourcingService.add_rfq_quote_lines(*args, **kwargs)

    @classmethod
    def build_line_comparison(cls, *args, **kwargs):
        from apps.procurement.line_sourcing import LineSourcingService

        return LineSourcingService.build_line_comparison(*args, **kwargs)

    @classmethod
    def award_pr_lines(cls, *args, **kwargs):
        from apps.procurement.line_sourcing import LineSourcingService

        return LineSourcingService.award_pr_lines(*args, **kwargs)

    @classmethod
    def create_pos_from_awards(cls, *args, **kwargs):
        from apps.procurement.line_sourcing import LineSourcingService

        return LineSourcingService.create_pos_from_awards(*args, **kwargs)

    @classmethod
    def assess_po_amount(cls, po: PurchaseOrder) -> AmountAssessment:
        """Sum of PO line commitments. Default unit_price=0 from unpriced create is unknown."""
        lines = list(po.lines.all())
        if not lines:
            return AmountAssessment(None, "", "empty_request", "no_po_lines")
        # Unpriced create_po_from_pr leaves every line at default 0 — not a free order.
        if all(Decimal(str(line.unit_price or 0)) == 0 for line in lines):
            return AmountAssessment(None, "", "amount_unknown", "po_lines_unpriced")
        total = Decimal("0")
        for line in lines:
            price = Decimal(str(line.unit_price))
            total += Decimal(str(line.qty or 0)) * price
        return AmountAssessment(
            _quantize_money(total),
            _SUPPORTED_CURRENCY,
            "ok",
            "po_line_unit_price_x_qty",
        )

    @classmethod
    def pr_committed_amount(cls, pr: PurchaseRequest) -> AmountAssessment:
        """Combined non-cancelled PO commitments for a PR (known lines only)."""
        total = Decimal("0")
        any_known = False
        for po in pr.purchase_orders.exclude(status__in=_INACTIVE_PO_STATUSES):
            assessed = cls.assess_po_amount(po)
            if not assessed.is_known:
                return AmountAssessment(
                    None,
                    "",
                    assessed.reason or "amount_unknown",
                    "mixed_or_unpriced_po_commitment",
                )
            any_known = True
            total += assessed.amount
        if not any_known:
            return AmountAssessment(_quantize_money(Decimal("0")), _SUPPORTED_CURRENCY, "ok", "no_pos")
        return AmountAssessment(_quantize_money(total), _SUPPORTED_CURRENCY, "ok", "sum_po_commitments")

    @classmethod
    def latest_pr_approval(cls, pr: PurchaseRequest) -> ApprovalRequest | None:
        ct = ContentType.objects.get_for_model(PurchaseRequest)
        return (
            ApprovalRequest.objects.filter(
                workflow_code=WF_PROCUREMENT_PR,
                entity_type=ct,
                entity_id=pr.pk,
                status=ApprovalStatus.APPROVED,
            )
            .order_by("-decided_at", "-id")
            .first()
        )

    @classmethod
    def latest_pr_approval_payload(cls, pr: PurchaseRequest) -> dict:
        req = cls.latest_pr_approval(pr)
        return dict(req.payload or {}) if req else {}

    @classmethod
    def verified_spending_ceiling(cls, payload: dict | None) -> Decimal | None:
        """Return a spending ceiling only when provenance is demonstrably monetary.

        A bare numeric amount with currency=AZN is insufficient (legacy qty labels).
        Requires decision_scope=process_and_amount and a verified amount_basis.
        """
        if not payload:
            return None
        if (payload.get("decision_scope") or "") != "process_and_amount":
            return None
        if (payload.get("amount_basis") or "") not in VERIFIED_MONETARY_BASES:
            return None
        raw = (payload.get("amount") or "").strip()
        currency = (payload.get("currency") or "").strip().upper()
        if not raw or currency != _SUPPORTED_CURRENCY:
            return None
        try:
            return _quantize_money(Decimal(raw))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @classmethod
    def commitment_fingerprint(
        cls,
        pr: PurchaseRequest,
        *,
        unit_price,
        currency: str = _SUPPORTED_CURRENCY,
        supplier_id=None,
        quote_id=None,
    ) -> str:
        lines = [
            [line.pk, format(Decimal(str(line.qty or 0)), "f"), line.sku_id]
            for line in pr.lines.order_by("id")
        ]
        blob = json.dumps(
            {
                "pr_id": pr.pk,
                "quote_id": quote_id,
                "supplier_id": supplier_id,
                "unit_price": format(_quantize_money(Decimal(str(unit_price))), "f"),
                "currency": (currency or _SUPPORTED_CURRENCY).upper(),
                "lines": lines,
                "tax_basis": "unspecified",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:40]

    @classmethod
    def iter_unverified_historical_approvals(cls):
        """Approved PR decisions that carry an amount without verified monetary provenance."""
        for req in ApprovalRequest.objects.filter(
            workflow_code=WF_PROCUREMENT_PR,
            status=ApprovalStatus.APPROVED,
        ).order_by("id"):
            payload = req.payload or {}
            raw = (payload.get("amount") or "").strip()
            if not raw:
                continue
            if cls.verified_spending_ceiling(payload) is not None:
                continue
            yield {
                "approval_id": req.pk,
                "pr_id": payload.get("pr_id") or req.entity_id,
                "pr_code": payload.get("code") or "",
                "amount": raw,
                "currency": payload.get("currency") or "",
                "decision_scope": payload.get("decision_scope") or "",
                "amount_basis": payload.get("amount_basis") or "",
                "reason": "unverified_or_legacy_quantity_payload",
                "decided_at": req.decided_at,
            }

    @classmethod
    def actor_within_approval_limit(cls, actor, amount: Decimal | None) -> bool:
        """Legacy helper — amount-based self-authorization is retired.

        Always False for spending authority. Kept for call-site compatibility /
        reporting only; PO issue requires a matching Management commitment.
        """
        return False

    @classmethod
    def approval_limit_for(cls, actor) -> PurchaseApprovalLimit | None:
        role = getattr(actor, "role", None) if actor else None
        if not role:
            return None
        return PurchaseApprovalLimit.objects.filter(role=role, is_active=True).first()

    @classmethod
    def assert_can_approve_pr(cls, actor, pr: PurchaseRequest) -> None:
        """Process-path submit/escalate only — no local spending authority."""
        from apps.accounts.models import Role
        from apps.procurement.models import PRSource

        role = getattr(actor, "role", None) if actor else None
        if role == Role.MANAGEMENT:
            raise DomainError("Rəhbərlik satınalmanı təsdiq hub ilə idarə edir.")
        if role == Role.ADMIN:
            return
        if role == Role.SERVICE_DESK:
            if pr.source not in {PRSource.WO, PRSource.LOW_STOCK}:
                raise DomainError(
                    "Təchizat yalnız iş əmri / ehtiyat çatışmazlığı satınalmalarını irəli apara bilər."
                )
            return
        raise DomainError("Satınalma təsdiqi üçün icazəniz yoxdur.")

    @classmethod
    def _escalation_message(cls, reason: str) -> str:
        return {
            "amount_unknown": "Satınalma məbləği müəyyən edilməyib — Management təsdiqi gözlənilir.",
            "empty_request": "Satınalma sətiri yoxdur — Management təsdiqi gözlənilir.",
            "limit_missing": "Satınalma limiti təyin olunmayıb — Management təsdiqi gözlənilir.",
            "over_limit": "Satınalma limiti aşılır — Management təsdiqi gözlənilir.",
            "currency_unsupported": "Dəstəklənməyən valyuta — Management təsdiqi gözlənilir.",
        }.get(reason, "Satınalma Management təsdiqi gözlənilir.")

    @classmethod
    def approve_pr(cls, pr: PurchaseRequest, *, actor=None) -> PurchaseRequest:
        """Escalate every PR to Management — no amount-based self-authorization.

        Process-only PR approval (via Management hub) grants no spending authority;
        priced PO issue still requires a matching ``procurement.commitment``.
        Escalation commits the ApprovalRequest before raising so the queue survives.
        """
        cls.require(pr.status in {PRStatus.DRAFT, PRStatus.SUBMITTED}, "PR təsdiq üçün uyğun deyil.")
        cls.assert_can_approve_pr(actor, pr)
        assessed = cls.assess_pr_approval_amount(pr)
        if not assessed.is_known:
            reason = assessed.reason or "amount_unknown"
        else:
            reason = "over_limit"
        cls._escalate_pr_for_management(pr, actor=actor, assessed=assessed, reason=reason)
        raise DomainError(cls._escalation_message(reason))

    @classmethod
    @transaction.atomic
    def _approve_pr_immediate(
        cls, pr: PurchaseRequest, *, actor=None, assessed: AmountAssessment | None = None
    ) -> PurchaseRequest:
        assessed = assessed or cls.assess_pr_approval_amount(pr)
        payload = {
            "pr_id": pr.pk,
            "code": pr.code,
            "amount": str(assessed.amount) if assessed.is_known else "",
            "currency": assessed.currency if assessed.is_known else "",
            "amount_basis": assessed.basis,
            "escalation_reason": "",
            "source": pr.source,
            "decision_scope": "process_and_amount" if assessed.is_known else "process_only",
        }
        ct = ContentType.objects.get_for_model(PurchaseRequest)
        pending = ApprovalRequest.objects.select_for_update().filter(
            workflow_code="procurement.pr",
            status=ApprovalStatus.PENDING,
            entity_type=ct,
            entity_id=pr.pk,
        )
        for old in pending:
            ApprovalService.cancel(
                old,
                actor=actor,
                comment="Yerli/Admin təsdiqi — əvvəlki eskalasiya ləğv edildi.",
            )
        req = ApprovalService.request(
            workflow_code="procurement.pr",
            requested_by=actor,
            entity=pr,
            payload=payload,
        )
        ApprovalService.decide(req, approved=True, decided_by=actor, comment="PR approved")
        pr.status = PRStatus.APPROVED
        pr.save(update_fields=["status"])
        bus.emit(
            bus.PURCHASE_APPROVED,
            payload={"pr_id": pr.pk, "code": pr.code, "entity_model": "purchase_request"},
            actor=actor,
            event_key=f"purchase.approved.{pr.pk}",
        )
        return pr

    @classmethod
    @transaction.atomic
    def _escalate_pr_for_management(
        cls,
        pr: PurchaseRequest,
        *,
        actor=None,
        assessed: AmountAssessment | None = None,
        amount=None,
        reason: str = "amount_unknown",
    ) -> ApprovalRequest:
        ct = ContentType.objects.get_for_model(PurchaseRequest)
        existing = ApprovalRequest.objects.filter(
            workflow_code="procurement.pr",
            status=ApprovalStatus.PENDING,
            entity_type=ct,
            entity_id=pr.pk,
        ).first()
        if existing is not None:
            return existing
        if pr.status == PRStatus.DRAFT:
            pr.status = PRStatus.SUBMITTED
            pr.save(update_fields=["status"])
        if assessed is None:
            if amount is None:
                assessed = cls.assess_pr_approval_amount(pr)
            else:
                assessed = AmountAssessment(
                    _quantize_money(Decimal(str(amount))),
                    _SUPPORTED_CURRENCY,
                    "ok",
                    "legacy_amount_arg",
                )
        limit = cls.approval_limit_for(actor)
        return ApprovalService.request(
            workflow_code="procurement.pr",
            requested_by=actor,
            entity=pr,
            payload={
                "pr_id": pr.pk,
                "code": pr.code,
                "amount": str(assessed.amount) if assessed.is_known else "",
                "currency": assessed.currency if assessed.is_known else "",
                "amount_basis": assessed.basis,
                "escalation_reason": reason,
                "limit_amount": str(limit.max_amount) if limit else "",
                "limit_currency": _SUPPORTED_CURRENCY if limit else "",
                "source": pr.source,
                "decision_scope": "process_and_amount" if assessed.is_known else "process_only",
            },
        )

    @classmethod
    def find_matching_commitment(
        cls,
        pr: PurchaseRequest,
        *,
        fingerprint: str,
        status: str = ApprovalStatus.APPROVED,
    ) -> ApprovalRequest | None:
        ct = ContentType.objects.get_for_model(PurchaseRequest)
        qs = ApprovalRequest.objects.filter(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            status=status,
            entity_type=ct,
            entity_id=pr.pk,
            payload__fingerprint=fingerprint,
        ).order_by("-decided_at", "-id")
        for req in qs:
            payload = req.payload or {}
            if status == ApprovalStatus.APPROVED and payload.get("consumed_po_id"):
                continue
            return req
        return None

    @classmethod
    def commitment_still_matches_current_terms(cls, req: ApprovalRequest) -> bool:
        """True when an approved/pending commitment fingerprint matches current PR lines."""
        payload = req.payload or {}
        fingerprint = (payload.get("fingerprint") or "").strip()
        unit_price = payload.get("unit_price")
        if not fingerprint or unit_price in (None, ""):
            return False
        pr = PurchaseRequest.objects.filter(pk=req.entity_id).first()
        if pr is None:
            return False
        current = cls.commitment_fingerprint(
            pr,
            unit_price=unit_price,
            currency=(payload.get("currency") or _SUPPORTED_CURRENCY),
            supplier_id=payload.get("supplier_id"),
            quote_id=payload.get("quote_id"),
        )
        return current == fingerprint

    @classmethod
    def list_issuable_commitments(cls) -> list[ApprovalRequest]:
        """Approved, unused supplier commitments that still match current terms.

        Counting unit: one row per supplier commitment (not per PR). A PR with
        supplier A approved and B pending contributes only A's row.
        """
        ct = ContentType.objects.get_for_model(PurchaseRequest)
        rows = (
            ApprovalRequest.objects.filter(
                workflow_code=WF_PROCUREMENT_COMMITMENT,
                status=ApprovalStatus.APPROVED,
                entity_type=ct,
            )
            .select_related("requested_by")
            .order_by("-decided_at", "-id")
        )
        ready: list[ApprovalRequest] = []
        seen: set[int] = set()
        for req in rows:
            payload = req.payload or {}
            if payload.get("consumed_po_id"):
                continue
            if not cls.commitment_still_matches_current_terms(req):
                continue
            fingerprint = payload.get("fingerprint") or ""
            matched = cls.find_matching_commitment(
                PurchaseRequest.objects.get(pk=req.entity_id),
                fingerprint=fingerprint,
                status=ApprovalStatus.APPROVED,
            )
            if matched is None or matched.pk != req.pk:
                continue
            if req.pk in seen:
                continue
            seen.add(req.pk)
            ready.append(req)
        return ready

    @classmethod
    def list_pending_procurement_approvals(
        cls, *, kind: str = "all"
    ) -> list[ApprovalRequest]:
        """Pending process-PR and/or supplier-commitment requests (Supply RO inbox)."""
        ct = ContentType.objects.get_for_model(PurchaseRequest)
        codes: list[str]
        if kind == "commitment":
            codes = [WF_PROCUREMENT_COMMITMENT]
        elif kind == "pr":
            codes = [WF_PROCUREMENT_PR]
        else:
            codes = [WF_PROCUREMENT_PR, WF_PROCUREMENT_COMMITMENT]
        return list(
            ApprovalRequest.objects.filter(
                workflow_code__in=codes,
                status=ApprovalStatus.PENDING,
                entity_type=ct,
            )
            .select_related("requested_by")
            .order_by("created_at", "id")
        )

    @classmethod
    @transaction.atomic
    def escalate_commitment_for_management(
        cls,
        pr: PurchaseRequest,
        *,
        assessed: AmountAssessment,
        actor=None,
        quote: RFQQuote | None = None,
        unit_price=None,
        supplier_id=None,
        reason: str = "over_limit",
    ) -> ApprovalRequest:
        """Submit a priced commitment for Management financial approval (idempotent)."""
        cls.require(assessed.is_known, "Qiymətli öhdəlik üçün məbləğ tələb olunur.")
        price = unit_price if unit_price is not None else (
            quote.unit_price if quote is not None else None
        )
        cls.require(price is not None, "Öhdəlik üçün vahid qiymət tələb olunur.")
        supplier_id = supplier_id or (quote.supplier_party_id if quote else None)
        quote_id = quote.pk if quote else None
        fingerprint = cls.commitment_fingerprint(
            pr,
            unit_price=price,
            currency=assessed.currency,
            supplier_id=supplier_id,
            quote_id=quote_id,
        )
        existing_pending = cls.find_matching_commitment(
            pr, fingerprint=fingerprint, status=ApprovalStatus.PENDING
        )
        if existing_pending is not None:
            return existing_pending

        limit = cls.approval_limit_for(actor)
        line_rows = [
            {
                "line_id": line.pk,
                "description": line.description,
                "qty": format(Decimal(str(line.qty or 0)), "f"),
                "sku_id": line.sku_id,
            }
            for line in pr.lines.order_by("id")
        ]
        return ApprovalService.request(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            requested_by=actor,
            entity=pr,
            payload={
                "pr_id": pr.pk,
                "code": pr.code,
                "quote_id": quote_id,
                "supplier_id": supplier_id,
                "unit_price": format(_quantize_money(Decimal(str(price))), "f"),
                "amount": str(assessed.amount),
                "currency": assessed.currency,
                "amount_basis": assessed.basis,
                "decision_scope": "process_and_amount",
                "tax_basis": "unspecified",
                "fingerprint": fingerprint,
                "lines": line_rows,
                "escalation_reason": reason,
                "limit_amount": str(limit.max_amount) if limit else "",
                "limit_currency": _SUPPORTED_CURRENCY if limit else "",
                "source": pr.source,
            },
        )

    @classmethod
    @transaction.atomic
    def decide_management_commitment(
        cls,
        approval: ApprovalRequest,
        *,
        approved: bool,
        actor=None,
        comment: str = "",
    ) -> ApprovalRequest:
        locked = ApprovalRequest.objects.select_for_update().get(pk=approval.pk)
        cls.require(
            locked.workflow_code == WF_PROCUREMENT_COMMITMENT,
            "Satınalma öhdəlik təsdiqi deyil.",
        )
        return ApprovalService.decide(
            locked, approved=approved, decided_by=actor, comment=comment
        )

    @classmethod
    def assert_commitment_allowed(
        cls,
        pr: PurchaseRequest,
        *,
        additional: AmountAssessment,
        actor=None,
        quote: RFQQuote | None = None,
        unit_price=None,
        supplier_id=None,
        escalate: bool = True,
    ) -> ApprovalRequest | None:
        """Enforce monetary commitment when a comparable amount exists.

        Verified spending ceilings require decision_scope + amount_basis provenance.
        Legacy quantity-as-AZN payloads never authorize new PO spend.
        Over-limit priced attempts escalate to procurement.commitment when escalate=True.
        Returns the matching approved commitment when one authorizes this issue.
        """
        from apps.audit.services import log_action

        if additional.reason == "currency_unsupported":
            raise DomainError(cls._escalation_message("currency_unsupported"))
        if not additional.is_known:
            # Unpriced issue blocked — draft-only path uses create_po_from_pr(status=DRAFT).
            raise DomainError(
                "Qiymətsiz satınalma buraxıla bilməz — yalnız qaralama; "
                "podratçı + qiymətli sətirlər və Management təsdiqi tələb olunur."
            )

        committed = cls.pr_committed_amount(pr)
        if not committed.is_known:
            raise DomainError("Mövcud PO öhdəlikləri müəyyən edilməyib.")
        projected = _quantize_money(committed.amount + additional.amount)

        price = unit_price if unit_price is not None else (
            quote.unit_price if quote is not None else None
        )
        supplier_id = supplier_id or (quote.supplier_party_id if quote else None)
        quote_id = quote.pk if quote else None
        if price is None:
            raise DomainError(
                "Qiymətsiz satınalma buraxıla bilməz — yalnız qaralama; "
                "podratçı + qiymətli sətirlər və Management təsdiqi tələb olunur."
            )

        fingerprint = cls.commitment_fingerprint(
            pr,
            unit_price=price,
            currency=additional.currency,
            supplier_id=supplier_id,
            quote_id=quote_id,
        )
        matched = cls.find_matching_commitment(
            pr, fingerprint=fingerprint, status=ApprovalStatus.APPROVED
        )
        if matched is not None:
            payload = matched.payload or {}
            # Revalidate terms — changed supplier/price after approval must not issue.
            if supplier_id is not None and payload.get("supplier_id") not in (
                None,
                supplier_id,
            ):
                raise DomainError(
                    "Təsdiqlənmiş podratçı dəyişib — yeni Management təsdiqi tələb olunur."
                )
            if format(_quantize_money(Decimal(str(price))), "f") != str(
                payload.get("unit_price") or ""
            ):
                # Fingerprint already encodes price; mismatch means stale payload.
                if payload.get("fingerprint") and payload.get("fingerprint") != fingerprint:
                    raise DomainError(
                        "Təsdiqlənmiş təklif şərtləri dəyişib — yeni Management təsdiqi tələb olunur."
                    )
            ceiling = cls.verified_spending_ceiling(matched.payload)
            if ceiling is not None and projected <= ceiling:
                return matched
            if ceiling is not None and projected > ceiling:
                raise DomainError(
                    f"Təsdiq olunmuş öhdəlik limiti aşılır ({projected} > {ceiling} AZN)."
                )
            # Commitment without verified ceiling still authorizes exact fingerprint match.
            if (matched.payload or {}).get("fingerprint") == fingerprint:
                return matched

        # process_only PR approval never grants spending authority (prior_ceiling ignored).
        log_action(
            action="procurement.commitment.required",
            actor=actor,
            entity=pr,
            new_values={
                "projected": str(projected),
                "additional": str(additional.amount),
                "currency": additional.currency,
                "fingerprint": fingerprint,
                "quote_id": quote_id,
            },
        )

        reason = "over_limit"
        if escalate and fingerprint:
            pending = cls.find_matching_commitment(
                pr, fingerprint=fingerprint, status=ApprovalStatus.PENDING
            )
            if pending is None:
                pending = cls.escalate_commitment_for_management(
                    pr,
                    assessed=additional,
                    actor=actor,
                    quote=quote,
                    unit_price=price,
                    supplier_id=supplier_id,
                    reason=reason,
                )
            raise DomainError(
                f"{cls._escalation_message(reason)} "
                f"(öhdəlik sorğusu #{pending.pk}: {additional.amount} {additional.currency})."
            )
        raise DomainError(
            f"Satınalma öhdəliyi üçün Management təsdiqi tələb olunur ({projected} AZN)."
        )

    @classmethod
    @transaction.atomic
    def apply_management_pr_decision(cls, pr: PurchaseRequest, *, approved: bool, actor=None) -> PurchaseRequest:
        locked = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
        cls.require(locked.status == PRStatus.SUBMITTED, "PR qərar üçün uyğun deyil.")
        if approved:
            locked.status = PRStatus.APPROVED
            locked.save(update_fields=["status"])
            bus.emit(
                bus.PURCHASE_APPROVED,
                payload={"pr_id": locked.pk, "code": locked.code, "entity_model": "purchase_request"},
                actor=actor,
                event_key=f"purchase.approved.{locked.pk}",
            )
        else:
            locked.status = PRStatus.REJECTED
            locked.save(update_fields=["status"])
        pr.status = locked.status
        return locked

    @classmethod
    @transaction.atomic
    def decide_management_pr(
        cls,
        approval: ApprovalRequest,
        *,
        approved: bool,
        actor=None,
        comment: str = "",
    ) -> PurchaseRequest:
        """Single atomic path: decide ApprovalRequest then apply PR outcome."""
        locked_req = ApprovalRequest.objects.select_for_update().get(pk=approval.pk)
        cls.require(
            locked_req.workflow_code == "procurement.pr",
            "Satınalma təsdiqi deyil.",
        )
        cls.require(
            locked_req.status == ApprovalStatus.PENDING,
            "Yalnız gözləyən sorğu qərar verilə bilər.",
        )
        pr = locked_req.entity
        if pr is None:
            pr_id = (locked_req.payload or {}).get("pr_id")
            pr = PurchaseRequest.objects.filter(pk=pr_id).first()
        cls.require(pr is not None, "Purchase Request tapılmadı.")
        ApprovalService.decide(
            locked_req, approved=approved, decided_by=actor, comment=comment
        )
        return cls.apply_management_pr_decision(pr, approved=approved, actor=actor)

    @classmethod
    @transaction.atomic
    def create_rfq_from_pr(cls, pr: PurchaseRequest, *, actor=None, title="") -> RFQ:
        from apps.audit.services import log_action

        if actor is not None:
            cls.assert_can_edit_procurement(actor)
        cls.require(
            pr.status in {PRStatus.APPROVED, PRStatus.SUBMITTED, PRStatus.ORDERED},
            "RFQ üçün PR uyğun deyil.",
        )
        rfq = RFQ.objects.create(
            code=_next_code("RFQ", RFQ),
            title=(title or pr.title)[:200],
            pr=pr,
        )
        log_action(
            action="procurement.rfq.create",
            actor=actor,
            entity=rfq,
            new_values={"code": rfq.code, "pr": pr.code},
        )
        return rfq

    @classmethod
    @transaction.atomic
    def add_rfq_quote(
        cls, rfq: RFQ, *, supplier_party, unit_price, lead_time_days=0, notes="", actor=None
    ) -> RFQQuote:
        from apps.audit.services import log_action
        from apps.parties.models import PartyRoleCode

        if actor is not None:
            cls.assert_can_edit_procurement(actor)
        cls.require(supplier_party is not None, "Podratçı seçilməlidir.")
        if not supplier_party.roles.filter(role=PartyRoleCode.SUPPLIER).exists():
            raise DomainError("Seçilmiş party podratçı deyil.")
        if unit_price is None or str(unit_price).strip() == "":
            raise DomainError("Qiymət tələb olunur — boş qiymət sıfır təklif sayılmır.")
        price = Decimal(str(unit_price))
        cls.require(price >= 0, "Qiymət mənfi ola bilməz.")
        quote = RFQQuote.objects.create(
            rfq=rfq,
            supplier_party=supplier_party,
            unit_price=price,
            lead_time_days=int(lead_time_days or 0),
            notes=notes or "",
        )
        log_action(
            action="procurement.rfq.quote",
            actor=actor,
            entity=rfq,
            new_values={"quote_id": quote.pk, "unit_price": str(price)},
        )
        return quote

    @classmethod
    def _mark_commitment_consumed(cls, commitment: ApprovalRequest | None, po: PurchaseOrder) -> None:
        if commitment is None:
            return
        locked = ApprovalRequest.objects.select_for_update().get(pk=commitment.pk)
        payload = dict(locked.payload or {})
        if payload.get("consumed_po_id"):
            return
        payload["consumed_po_id"] = po.pk
        locked.payload = payload
        locked.save(update_fields=["payload", "updated_at"])

    @classmethod
    def _priced_assessment(
        cls, pr: PurchaseRequest, unit_price, line_qtys: dict | None = None
    ) -> AmountAssessment:
        price = _quantize_money(Decimal(str(unit_price)))
        resolved = cls.resolve_po_line_qtys(pr, line_qtys)
        total = Decimal("0")
        for qty in resolved.values():
            total += qty * price
        return AmountAssessment(
            _quantize_money(total),
            _SUPPORTED_CURRENCY,
            "ok",
            "priced_po_unit_price_x_pr_qty",
        )

    @classmethod
    def _escalate_priced_block(
        cls,
        pr: PurchaseRequest,
        *,
        assessed: AmountAssessment,
        actor=None,
        quote: RFQQuote | None = None,
        unit_price=None,
        supplier_id=None,
    ) -> None:
        """Commit a Management commitment request, then raise (must run outside write txn)."""
        cls.assert_commitment_allowed(
            pr,
            additional=assessed,
            actor=actor,
            quote=quote,
            unit_price=unit_price,
            supplier_id=supplier_id,
            escalate=True,
        )

    @classmethod
    def select_rfq_quote_and_create_po(cls, quote: RFQQuote, *, actor=None) -> PurchaseOrder:
        if actor is not None:
            cls.assert_can_edit_procurement(actor)
        rfq = quote.rfq
        cls.require(rfq.pr_id, "RFQ Purchase Request-ə bağlı deyil.")
        cls.require(quote.supplier_party_id, "Podratçı seçilməlidir.")

        try:
            with transaction.atomic():
                pr = PurchaseRequest.objects.select_for_update().get(pk=rfq.pr_id)
                cls.require(
                    pr.status in {PRStatus.APPROVED, PRStatus.ORDERED},
                    "Yalnız təsdiqlənmiş PR-dən PO.",
                )
                quote = RFQQuote.objects.select_for_update().get(pk=quote.pk)
                assessed = cls.assess_quote_amount(quote, pr)
                commitment = cls.assert_commitment_allowed(
                    pr,
                    additional=assessed,
                    actor=actor,
                    quote=quote,
                    unit_price=quote.unit_price,
                    supplier_id=quote.supplier_party_id,
                    escalate=False,
                )
                if commitment is not None:
                    payload = commitment.payload or {}
                    if format(_quantize_money(Decimal(str(quote.unit_price))), "f") != str(
                        payload.get("unit_price") or ""
                    ):
                        raise DomainError(
                            "Təsdiqlənmiş təklif şərtləri dəyişib — yeni Management təsdiqi tələb olunur."
                        )
                    if quote.supplier_party_id != payload.get("supplier_id"):
                        raise DomainError(
                            "Təsdiqlənmiş podratçı dəyişib — yeni Management təsdiqi tələb olunur."
                        )
                RFQQuote.objects.filter(rfq=rfq, is_selected=True).update(is_selected=False)
                quote.is_selected = True
                quote.save(update_fields=["is_selected"])
                # Legacy header path: block if active line awards exist for this PR
                if pr.line_awards.filter(is_active=True, po_line__isnull=True).exists():
                    raise DomainError(
                        "PR-də sətir mükafatları var — header təklifdən PO əvəzinə "
                        "mükafatlardan PO yaradın."
                    )
                return cls.create_po_from_pr(
                    pr,
                    supplier_party=quote.supplier_party,
                    actor=actor,
                    unit_price=quote.unit_price,
                    skip_commitment_check=True,
                    commitment=commitment,
                )
        except DomainError as exc:
            # Over-limit / missing limit: persist commitment request outside the rolled-back txn.
            msg = str(exc)
            if "limit" in msg.lower() or "öhdəlik" in msg.lower() or "Management" in msg:
                pr = PurchaseRequest.objects.get(pk=rfq.pr_id)
                quote = RFQQuote.objects.get(pk=quote.pk)
                assessed = cls.assess_quote_amount(quote, pr)
                cls._escalate_priced_block(
                    pr,
                    assessed=assessed,
                    actor=actor,
                    quote=quote,
                    unit_price=quote.unit_price,
                    supplier_id=quote.supplier_party_id,
                )
            raise

    @classmethod
    def create_po_from_pr(
        cls,
        pr: PurchaseRequest,
        *,
        supplier_party=None,
        actor=None,
        unit_price=None,
        skip_commitment_check: bool = False,
        commitment: ApprovalRequest | None = None,
        line_qtys: dict | None = None,
    ) -> PurchaseOrder:
        from apps.audit.services import log_action
        from apps.parties.models import PartyRoleCode

        if actor is not None:
            cls.assert_can_edit_procurement(actor)
        cls.require(supplier_party is not None, "Podratçı seçilməlidir.")
        if not supplier_party.roles.filter(role=PartyRoleCode.SUPPLIER).exists():
            raise DomainError("Seçilmiş party podratçı deyil.")

        priced = unit_price is not None
        matched = commitment
        pr_id = pr.pk

        try:
            with transaction.atomic():
                locked = PurchaseRequest.objects.select_for_update().get(pk=pr_id)
                cls.require(
                    locked.status in {PRStatus.APPROVED, PRStatus.ORDERED},
                    "Yalnız təsdiqlənmiş PR-dən PO.",
                )
                resolved_qtys = cls.resolve_po_line_qtys(locked, line_qtys)
                # Direct PO must not bypass active line awards awaiting issuance
                if locked.line_awards.filter(is_active=True, po_line__isnull=True).exists():
                    raise DomainError(
                        "PR-də sətir mükafatları var — birbaşa PO əvəzinə "
                        "mükafatlardan PO yaradın."
                    )
                if priced and not skip_commitment_check:
                    assessed = cls._priced_assessment(locked, unit_price, line_qtys=line_qtys)
                    matched = cls.assert_commitment_allowed(
                        locked,
                        additional=assessed,
                        actor=actor,
                        unit_price=unit_price,
                        supplier_id=getattr(supplier_party, "pk", None),
                        escalate=False,
                    )
                    if matched is None:
                        raise DomainError(
                            "Qiymətli PO üçün Management öhdəlik təsdiqi tələb olunur."
                        )
                elif priced and skip_commitment_check:
                    if matched is None:
                        raise DomainError(
                            "Qiymətli PO üçün Management öhdəlik təsdiqi tələb olunur."
                        )
                elif not priced:
                    # Unpriced record may exist only as draft — no issue / goods receipt.
                    matched = None

                po_status = POStatus.SENT if priced else POStatus.DRAFT
                po = PurchaseOrder.objects.create(
                    code=_next_code("PO", PurchaseOrder),
                    supplier_party=supplier_party,
                    status=po_status,
                    pr=locked,
                    ordered_at=timezone.localdate() if priced else None,
                )
                price_value = (
                    _quantize_money(Decimal(str(unit_price))) if priced else None
                )
                lines_by_id = {ln.pk: ln for ln in locked.lines.all()}
                for line_id, qty in resolved_qtys.items():
                    line = lines_by_id[line_id]
                    POLine.objects.create(
                        po=po,
                        description=line.description,
                        sku=line.sku,
                        qty=qty,
                        unit_price=price_value if price_value is not None else Decimal("0"),
                    )
                if priced and locked.status == PRStatus.APPROVED:
                    locked.status = PRStatus.ORDERED
                    locked.save(update_fields=["status"])
                if priced:
                    cls._mark_commitment_consumed(matched, po)
                log_action(
                    action="procurement.po.create",
                    actor=actor,
                    entity=po,
                    new_values={
                        "code": po.code,
                        "pr": locked.code,
                        "supplier": str(supplier_party),
                        "unit_price": str(price_value) if price_value is not None else "",
                        "commitment_id": matched.pk if matched else None,
                    },
                )
                if locked.requested_by_id:
                    from apps.comms.services import notify_in_app

                    requester = locked.requested_by
                    if requester is not None and requester.is_active and (
                        actor is None or requester.pk != getattr(actor, "pk", None)
                    ):
                        notify_in_app(
                            user=requester,
                            message=f"PO yaradıldı: {po.code} (PR {locked.code})",
                            event_key=f"procurement.po.create.{po.pk}",
                        )
                pr.status = locked.status
                return po
        except DomainError as exc:
            if priced and not skip_commitment_check:
                msg = str(exc)
                if "limit" in msg.lower() or "öhdəlik" in msg.lower() or "Management" in msg:
                    locked = PurchaseRequest.objects.get(pk=pr_id)
                    assessed = cls._priced_assessment(locked, unit_price, line_qtys=line_qtys)
                    cls._escalate_priced_block(
                        locked,
                        assessed=assessed,
                        actor=actor,
                        unit_price=unit_price,
                        supplier_id=getattr(supplier_party, "pk", None),
                    )
            raise

    @classmethod
    @transaction.atomic
    def set_po_line_unit_price(cls, line: POLine, *, unit_price, actor=None) -> POLine:
        """Set PO line price. Issued POs cannot change terms without new Management approval.

        Draft PO: price may be set; goods receipt remains blocked until priced issue
        with a matching commitment.
        """
        from apps.audit.services import log_action

        if actor is not None:
            cls.assert_can_edit_procurement(actor)
        if unit_price is None or str(unit_price).strip() == "":
            raise DomainError("Qiymət tələb olunur.")
        price = _quantize_money(Decimal(str(unit_price)))
        cls.require(price >= 0, "Qiymət mənfi ola bilməz.")

        # Do not select_related nullable po.pr — Postgres rejects FOR UPDATE on outer joins.
        locked_line = POLine.objects.select_for_update().select_related("po").get(pk=line.pk)
        po = locked_line.po
        if po.status != POStatus.DRAFT:
            raise DomainError(
                "Buraxılmış PO şərtləri dəyişdirilə bilməz — yeni Management təsdiqi "
                "və yeni öhdəlik tələb olunur."
            )

        old = locked_line.unit_price
        locked_line.unit_price = price
        locked_line.save(update_fields=["unit_price"])
        log_action(
            action="procurement.po.line_price",
            actor=actor,
            entity=po,
            new_values={
                "line_id": locked_line.pk,
                "unit_price": str(price),
                "previous": str(old) if old is not None else "",
                "po_status": po.status,
            },
        )
        return locked_line

    @classmethod
    def _resolve_receive_mode(cls, *, receive_mode, line_qtys) -> str:
        mode = (receive_mode or "").strip().lower()
        if mode in {GoodsReceiptOperation.MODE_FULL, GoodsReceiptOperation.MODE_PARTIAL}:
            return mode
        # Backward compatible callers: None line_qtys = full remaining; explicit map = partial.
        if line_qtys is None:
            return GoodsReceiptOperation.MODE_FULL
        return GoodsReceiptOperation.MODE_PARTIAL

    @classmethod
    def _replay_existing_receipt(
        cls,
        existing: GoodsReceiptOperation,
        *,
        fingerprint: str,
        po_id: int,
        warehouse_id: int,
    ) -> PurchaseOrder:
        if existing.payload_fingerprint != fingerprint:
            raise DomainError("Qəbul əməliyyatı konflikti: eyni açar, fərqli məlumat.")
        if existing.po_id != po_id or existing.warehouse_id != warehouse_id:
            raise DomainError("Qəbul əməliyyatı konflikti: eyni açar, fərqli məlumat.")
        po = PurchaseOrder.objects.get(pk=existing.po_id)
        return _mark_receipt_replay(po)

    @classmethod
    @transaction.atomic
    def receive_po(
        cls,
        po: PurchaseOrder,
        *,
        warehouse,
        actor=None,
        line_qtys=None,
        operation_key: str | None = None,
        receive_mode: str | None = None,
    ) -> PurchaseOrder:
        """Receive PO into warehouse with PO locking and durable operation idempotency.

        ``line_qtys`` = {po_line_id: qty} for partial receive.
        ``receive_mode``: ``full`` (all remaining) or ``partial`` (explicit lines only).
        When ``operation_key`` is omitted a unique key is generated (non-idempotent caller).
        """
        if warehouse is None or not getattr(warehouse, "pk", None):
            raise DomainError("Anbar seçilməlidir.")
        if actor is not None:
            cls.assert_can_edit_procurement(actor)
        if getattr(po, "status", None) == POStatus.DRAFT:
            raise DomainError(
                "Qaralama PO üzrə qəbul edilə bilməz — əvvəlcə qiymətli buraxılış və Management təsdiqi."
            )

        mode = cls._resolve_receive_mode(receive_mode=receive_mode, line_qtys=line_qtys)
        raw_key = (operation_key or "").strip()
        op_key = raw_key or uuid.uuid4().hex
        po_id = int(getattr(po, "pk"))
        warehouse_id = int(warehouse.pk)

        if mode == GoodsReceiptOperation.MODE_PARTIAL:
            normalized = _normalize_line_qtys(line_qtys or {})
            if not normalized:
                raise DomainError("Qismən qəbul üçün ən azı bir müsbət miqdar daxil edin.")
        else:
            # Preserve "receive all remaining" meaning for retries — fingerprint ignores live balances.
            normalized = {}

        fingerprint = _receipt_payload_fingerprint(
            po_id=po_id,
            warehouse_id=warehouse_id,
            mode=mode,
            line_qtys=normalized if mode == GoodsReceiptOperation.MODE_PARTIAL else None,
        )

        existing = GoodsReceiptOperation.objects.filter(operation_key=op_key).first()
        if existing is not None:
            return cls._replay_existing_receipt(
                existing, fingerprint=fingerprint, po_id=po_id, warehouse_id=warehouse_id
            )

        # of=("self",) avoids FOR UPDATE on nullable outer joins (pr / sku).
        locked_po = (
            PurchaseOrder.objects.select_for_update(of=("self",)).select_related("pr").get(pk=po_id)
        )
        lines = list(
            POLine.objects.select_for_update(of=("self",))
            .select_related("sku")
            .filter(po_id=locked_po.pk)
            .order_by("pk")
        )

        existing = (
            GoodsReceiptOperation.objects.select_for_update()
            .filter(operation_key=op_key)
            .first()
        )
        if existing is not None:
            return cls._replay_existing_receipt(
                existing, fingerprint=fingerprint, po_id=po_id, warehouse_id=warehouse_id
            )

        cls.require(
            locked_po.status in _RECEIVABLE_PO_STATUSES,
            "PO qəbul üçün uyğun deyil.",
        )

        line_by_id = {ln.pk: ln for ln in lines}
        if mode == GoodsReceiptOperation.MODE_PARTIAL:
            foreign = set(normalized) - set(line_by_id)
            if foreign:
                raise DomainError("Qəbul sətiri bu PO-ya aid deyil.")

        planned: list[tuple[POLine, Decimal]] = []
        for line in lines:
            if not line.sku_id:
                continue
            remaining = (line.qty or Decimal("0")) - (line.received_qty or Decimal("0"))
            if remaining <= 0:
                continue
            if mode == GoodsReceiptOperation.MODE_PARTIAL:
                if line.pk not in normalized:
                    continue
                take = normalized[line.pk]
            else:
                take = remaining
            if take <= 0:
                continue
            if take > remaining:
                raise DomainError("Qəbul miqdarı qalan miqdardan çox ola bilməz.")
            planned.append((line, take))

        if not planned:
            raise DomainError("Qəbul ediləcək miqdar yoxdur.")

        taken_rows = [{"line_id": line.pk, "qty": format(take, "f")} for line, take in planned]
        try:
            GoodsReceiptOperation.objects.create(
                operation_key=op_key,
                po=locked_po,
                warehouse=warehouse,
                actor=actor if getattr(actor, "pk", None) else None,
                mode=mode,
                payload_fingerprint=fingerprint,
                lines_json=taken_rows,
            )
        except IntegrityError:
            existing = GoodsReceiptOperation.objects.filter(operation_key=op_key).first()
            if existing is None:
                raise
            return cls._replay_existing_receipt(
                existing, fingerprint=fingerprint, po_id=po_id, warehouse_id=warehouse_id
            )

        for line, take in planned:
            apply_movement(
                sku=line.sku,
                warehouse=warehouse,
                movement_type=StockMovementType.RECEIPT,
                quantity=take,
                reference=locked_po.code,
            )
            line.received_qty = (line.received_qty or Decimal("0")) + take
            line.save(update_fields=["received_qty"])

        incomplete = any(
            (ln.received_qty or Decimal("0")) < (ln.qty or Decimal("0"))
            for ln in lines
            if ln.sku_id
        )
        locked_po.status = POStatus.PARTIAL if incomplete else POStatus.RECEIVED
        locked_po.save(update_fields=["status"])

        if locked_po.pr_id:
            pr = locked_po.pr
            if pr is not None and pr.work_order_id:
                from apps.maintenance.costs import sync_procurement_cost

                sync_procurement_cost(pr.work_order)

        bus.emit(
            bus.PO_RECEIVED,
            payload={
                "po_id": locked_po.pk,
                "code": locked_po.code,
                "status": locked_po.status,
                "operation_key": op_key,
                "entity_model": "purchase_order",
            },
            actor=actor,
            event_key=f"po.received.{locked_po.pk}.op.{op_key}",
        )
        locked_po.receipt_replayed = False
        return locked_po
