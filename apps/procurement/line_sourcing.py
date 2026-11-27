"""Line-level RFQ invitation, quote, comparison, award, and multi-PO issuance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.services import DomainError
from apps.procurement.models import (
    ComparisonCoverage,
    POLine,
    POStatus,
    PRLine,
    PRLineAward,
    PRStatus,
    PurchaseOrder,
    PurchaseRequest,
    QuoteLineResponseStatus,
    RFQ,
    RFQDispatchChannel,
    RFQInvitation,
    RFQInvitationLine,
    RFQQuote,
    RFQQuoteLine,
)
from apps.procurement.services import (
    VERIFIED_MONETARY_BASES,
    AmountAssessment,
    ProcurementService,
    WF_PROCUREMENT_COMMITMENT,
    _SUPPORTED_CURRENCY,
    _quantize_money,
    _quantize_qty,
)


def _money_for_qty(
    *,
    qty: Decimal,
    unit_price: Decimal,
    vat_rate,
    price_includes_vat: bool,
) -> dict[str, Decimal | None]:
    unit = _quantize_money(Decimal(str(unit_price or 0)))
    raw = _quantize_money(_quantize_qty(qty) * unit)
    if vat_rate is None:
        return {
            "net": raw if not price_includes_vat else None,
            "vat": None,
            "gross": raw if price_includes_vat else None,
            "tax_basis": "unknown",
        }
    rate = Decimal(str(vat_rate))
    if price_includes_vat:
        gross = raw
        net = _quantize_money(gross / (Decimal("1") + rate))
        vat = _quantize_money(gross - net)
    else:
        net = raw
        vat = _quantize_money(net * rate)
        gross = _quantize_money(net + vat)
    return {"net": net, "vat": vat, "gross": gross, "tax_basis": "explicit_rate"}


def quote_line_amounts(line: RFQQuoteLine) -> dict[str, Decimal | None]:
    """Return net / vat / gross for a quoted line; unanswered → None amounts."""
    if line.response_status != QuoteLineResponseStatus.QUOTED:
        return {"net": None, "vat": None, "gross": None, "tax_basis": "unanswered"}
    return _money_for_qty(
        qty=Decimal(str(line.qty or 0)),
        unit_price=Decimal(str(line.unit_price or 0)),
        vat_rate=line.vat_rate,
        price_includes_vat=bool(line.price_includes_vat),
    )


def award_amounts(award: PRLineAward) -> dict[str, Decimal | None]:
    """Net/VAT/gross for an award portion (not the full quote line)."""
    return _money_for_qty(
        qty=Decimal(str(award.qty or 0)),
        unit_price=Decimal(str(award.unit_price or 0)),
        vat_rate=award.vat_rate,
        price_includes_vat=bool(award.price_includes_vat),
    )


def _build_request_text(rfq: RFQ, supplier, lines: list[tuple[PRLine, Decimal]]) -> str:
    rows = []
    for pr_line, qty in lines:
        sku = pr_line.sku.code if pr_line.sku_id else "—"
        rows.append(
            f"- #{pr_line.pk} {sku} | {pr_line.description} | {format(qty, 'f')} {pr_line.unit}"
        )
    body = "\n".join(rows)
    return (
        f"RFQ {rfq.code}\n"
        f"Supplier: {getattr(supplier, 'display_name', supplier)}\n"
        f"PR: {rfq.pr.code if rfq.pr_id else '—'}\n"
        f"Lines:\n{body}\n"
    )


@dataclass
class SupplierPOOutcome:
    supplier_id: int
    supplier_name: str
    status: str  # issued | awaiting_financial_approval | failed | skipped
    message: str = ""
    po: PurchaseOrder | None = None
    commitment_id: int | None = None


@dataclass
class ComparisonCell:
    coverage: str
    quote_line: RFQQuoteLine | None = None
    net: Decimal | None = None
    vat: Decimal | None = None
    gross: Decimal | None = None
    tax_basis: str = ""
    award_eligible: bool = False
    is_lowest: bool = False
    quoted_qty: Decimal | None = None
    remaining_qty: Decimal | None = None


@dataclass
class LineComparisonRow:
    pr_line: PRLine
    remaining_qty: Decimal
    cells: dict[int, ComparisonCell] = field(default_factory=dict)


class LineSourcingService:
    """Public entrypoints for line-level sourcing (delegated from ProcurementService)."""

    @classmethod
    def synthetic_vat_rate(cls) -> Decimal | None:
        """Test/demo rate only — live auth uses Finance-approved basis on the quote line."""
        raw = getattr(settings, "PROCUREMENT_QUOTE_VAT_RATE", None)
        if raw is None or raw == "":
            return None
        return Decimal(str(raw))

    @classmethod
    @transaction.atomic
    def invite_supplier_to_rfq(
        cls,
        rfq: RFQ,
        *,
        supplier_party,
        line_specs: list[dict],
        actor=None,
        dispatch_channel: str = RFQDispatchChannel.DRAFT,
        dispatch_ref: str = "",
        mark_dispatched: bool = False,
    ) -> RFQInvitation:
        from apps.audit.services import log_action
        from apps.parties.models import PartyRoleCode

        if actor is not None:
            ProcurementService.assert_can_edit_procurement(actor)
        ProcurementService.require(rfq.pr_id, "RFQ Purchase Request-ə bağlı deyil.")
        ProcurementService.require(supplier_party is not None, "Podratçı seçilməlidir.")
        if not supplier_party.roles.filter(role=PartyRoleCode.SUPPLIER).exists():
            raise DomainError("Seçilmiş party podratçı deyil.")

        pr = PurchaseRequest.objects.select_for_update().get(pk=rfq.pr_id)
        pr_lines = {ln.pk: ln for ln in pr.lines.all()}
        if not line_specs:
            raise DomainError("Dəvət üçün ən azı bir sətir seçilməlidir.")

        resolved: list[tuple[PRLine, Decimal]] = []
        seen: set[int] = set()
        for spec in line_specs:
            line_id = int(spec["pr_line_id"])
            if line_id in seen:
                raise DomainError("Eyni PR sətri dəvətdə təkrarlanıb.")
            seen.add(line_id)
            line = pr_lines.get(line_id)
            if line is None:
                raise DomainError("PR sətri tapılmadı.")
            qty = _quantize_qty(spec.get("qty", line.qty))
            if qty <= 0:
                raise DomainError("Dəvət miqdarı müsbət olmalıdır.")
            remaining = ProcurementService.pr_line_remaining_qty(line)
            if qty > remaining:
                raise DomainError(
                    f"Dəvət miqdarı qalan PR miqdarını aşır (sətir {line_id})."
                )
            resolved.append((line, qty))

        channel = (dispatch_channel or RFQDispatchChannel.DRAFT).strip()
        if channel not in RFQDispatchChannel.values:
            raise DomainError("Dispatch kanalı düzgün deyil.")

        # Amendment: deactivate prior active invitation for same supplier (keep evidence).
        prior = (
            RFQInvitation.objects.select_for_update()
            .filter(rfq=rfq, supplier_party=supplier_party, is_active=True)
            .first()
        )
        if prior is not None:
            prior.is_active = False
            prior.save(update_fields=["is_active"])

        request_text = _build_request_text(rfq, supplier_party, resolved)
        invitation = RFQInvitation(
            rfq=rfq,
            supplier_party=supplier_party,
            request_text=request_text,
            dispatch_channel=channel,
            dispatch_ref=(dispatch_ref or "")[:255],
            supersedes=prior,
            is_active=True,
            created_by=actor,
        )
        # Dispatched only with evidence: manual ref, or non-draft channel with ref/timestamp intent.
        evidence = bool((dispatch_ref or "").strip()) or (
            channel in {RFQDispatchChannel.EMAIL, RFQDispatchChannel.OUTBOX, RFQDispatchChannel.MANUAL}
            and mark_dispatched
        )
        if mark_dispatched and not evidence and channel == RFQDispatchChannel.DRAFT:
            raise DomainError("Dispatch sübutu olmadan dəvət göndərilmiş sayılmır.")
        if evidence and mark_dispatched:
            if channel == RFQDispatchChannel.DRAFT:
                channel = RFQDispatchChannel.MANUAL
                invitation.dispatch_channel = channel
            invitation.dispatched_at = timezone.now()
        invitation.save()
        for line, qty in resolved:
            RFQInvitationLine.objects.create(
                invitation=invitation, pr_line=line, qty=qty
            )
        log_action(
            action="procurement.rfq.invite",
            actor=actor,
            entity=rfq,
            new_values={
                "invitation_id": invitation.pk,
                "supplier_id": supplier_party.pk,
                "lines": [[ln.pk, format(q, "f")] for ln, q in resolved],
                "dispatched": invitation.is_dispatched,
                "supersedes": prior.pk if prior else None,
            },
        )
        return invitation

    @classmethod
    @transaction.atomic
    def add_rfq_quote_lines(
        cls,
        rfq: RFQ,
        *,
        supplier_party,
        line_responses: list[dict],
        actor=None,
        supplier_reference: str = "",
        valid_until=None,
        lead_time_days: int = 0,
        notes: str = "",
        invitation: RFQInvitation | None = None,
    ) -> RFQQuote:
        from apps.audit.services import log_action
        from apps.parties.models import PartyRoleCode

        if actor is not None:
            ProcurementService.assert_can_edit_procurement(actor)
        ProcurementService.require(supplier_party is not None, "Podratçı seçilməlidir.")
        if not supplier_party.roles.filter(role=PartyRoleCode.SUPPLIER).exists():
            raise DomainError("Seçilmiş party podratçı deyil.")

        inv = invitation
        if inv is None:
            inv = (
                RFQInvitation.objects.filter(
                    rfq=rfq, supplier_party=supplier_party, is_active=True
                )
                .prefetch_related("lines")
                .first()
            )
        if inv is None:
            raise DomainError("Bu podratçı üçün aktiv dəvət yoxdur.")
        if inv.supplier_party_id != supplier_party.pk:
            raise DomainError("Dəvət podratçısı uyğun gəlmir.")

        invited = {il.pr_line_id: il for il in inv.lines.all()}
        if not line_responses:
            raise DomainError("Ən azı bir sətir cavabı tələb olunur.")

        quote = RFQQuote.objects.create(
            rfq=rfq,
            invitation=inv,
            supplier_party=supplier_party,
            unit_price=Decimal("0"),
            currency=_SUPPORTED_CURRENCY,
            lead_time_days=int(lead_time_days or 0),
            notes=notes or "",
            supplier_reference=(supplier_reference or "")[:120],
            valid_until=valid_until,
        )
        for resp in line_responses:
            line_id = int(resp["pr_line_id"])
            if line_id not in invited:
                raise DomainError(
                    f"Sətir {line_id} bu podratçının dəvət əhatəsindən kənardır."
                )
            status = (resp.get("response_status") or QuoteLineResponseStatus.QUOTED).strip()
            if status not in QuoteLineResponseStatus.values:
                raise DomainError("Cavab statusu düzgün deyil.")
            inv_line = invited[line_id]
            pr_line = inv_line.pr_line
            if status == QuoteLineResponseStatus.UNANSWERED:
                RFQQuoteLine.objects.create(
                    quote=quote,
                    pr_line=pr_line,
                    qty=inv_line.qty,
                    unit=pr_line.unit,
                    currency=_SUPPORTED_CURRENCY,
                    unit_price=Decimal("0"),
                    response_status=QuoteLineResponseStatus.UNANSWERED,
                    vat_rate=None,
                    price_includes_vat=False,
                )
                continue
            # Explicit quoted — zero price allowed
            if resp.get("unit_price") is None or str(resp.get("unit_price")).strip() == "":
                raise DomainError(
                    "Qiymət tələb olunur — boş qiymət sıfır təklif sayılmır; "
                    "cavabsız üçün unanswered seçin."
                )
            price = _quantize_money(Decimal(str(resp["unit_price"])))
            if price < 0:
                raise DomainError("Qiymət mənfi ola bilməz.")
            qty = _quantize_qty(resp.get("qty", inv_line.qty))
            if qty <= 0:
                raise DomainError("Təklif miqdarı müsbət olmalıdır.")
            currency = (resp.get("currency") or _SUPPORTED_CURRENCY).strip().upper()
            vat_rate = resp.get("vat_rate", cls.synthetic_vat_rate())
            if vat_rate is not None and str(vat_rate).strip() != "":
                vat_rate = Decimal(str(vat_rate))
            else:
                vat_rate = None
            RFQQuoteLine.objects.create(
                quote=quote,
                pr_line=pr_line,
                qty=qty,
                unit=(resp.get("unit") or pr_line.unit)[:16],
                currency=currency,
                unit_price=price,
                vat_rate=vat_rate,
                price_includes_vat=bool(resp.get("price_includes_vat")),
                response_status=QuoteLineResponseStatus.QUOTED,
            )
        log_action(
            action="procurement.rfq.quote_lines",
            actor=actor,
            entity=rfq,
            new_values={"quote_id": quote.pk, "supplier_id": supplier_party.pk},
        )
        return quote

    @classmethod
    def build_line_comparison(cls, rfq: RFQ) -> dict[str, Any]:
        pr = rfq.pr
        if pr is None:
            return {"rows": [], "suppliers": []}
        invitations = list(
            RFQInvitation.objects.filter(rfq=rfq, is_active=True)
            .select_related("supplier_party")
            .prefetch_related("lines")
        )
        suppliers = [
            {"id": inv.supplier_party_id, "name": inv.supplier_party.display_name, "invitation": inv}
            for inv in invitations
        ]
        # Latest line-priced quote per supplier
        quotes = (
            RFQQuote.objects.filter(rfq=rfq, invitation__isnull=False)
            .prefetch_related("lines")
            .order_by("-id")
        )
        latest_by_supplier: dict[int, RFQQuote] = {}
        for q in quotes:
            if q.supplier_party_id and q.supplier_party_id not in latest_by_supplier:
                if q.lines.exists():
                    latest_by_supplier[q.supplier_party_id] = q

        invited_map: dict[int, set[int]] = {
            inv.supplier_party_id: {il.pr_line_id for il in inv.lines.all()}
            for inv in invitations
        }

        rows: list[LineComparisonRow] = []
        for pr_line in pr.lines.select_related("sku").order_by("id"):
            remaining = ProcurementService.pr_line_remaining_qty(pr_line)
            row = LineComparisonRow(pr_line=pr_line, remaining_qty=remaining)
            comparable: list[tuple[int, ComparisonCell]] = []
            for inv in invitations:
                sid = inv.supplier_party_id
                if pr_line.pk not in invited_map.get(sid, set()):
                    row.cells[sid] = ComparisonCell(coverage=ComparisonCoverage.NOT_INVITED)
                    continue
                quote = latest_by_supplier.get(sid)
                qline = None
                if quote is not None:
                    qline = next(
                        (ln for ln in quote.lines.all() if ln.pr_line_id == pr_line.pk),
                        None,
                    )
                if qline is None or qline.response_status == QuoteLineResponseStatus.UNANSWERED:
                    row.cells[sid] = ComparisonCell(
                        coverage=ComparisonCoverage.INVITED_UNANSWERED,
                        remaining_qty=remaining,
                    )
                    continue
                amounts = quote_line_amounts(qline)
                quoted_qty = Decimal(str(qline.qty or 0))
                already = ProcurementService.quote_line_awarded_qty(qline)
                offer_left = quoted_qty - already
                if offer_left < 0:
                    offer_left = Decimal("0")
                max_portion = min(remaining, offer_left)
                eligible = (
                    qline.response_status == QuoteLineResponseStatus.QUOTED
                    and max_portion > 0
                    and remaining > 0
                    and (qline.unit or "") == (pr_line.unit or "")
                    and (qline.currency or "").upper() == _SUPPORTED_CURRENCY
                    and amounts["tax_basis"] != "unknown"
                )
                cell = ComparisonCell(
                    coverage=ComparisonCoverage.QUOTED,
                    quote_line=qline,
                    net=amounts["net"],
                    vat=amounts["vat"],
                    gross=amounts["gross"],
                    tax_basis=amounts["tax_basis"],
                    award_eligible=eligible,
                    quoted_qty=quoted_qty,
                    remaining_qty=remaining,
                )
                row.cells[sid] = cell
                if eligible and amounts["gross"] is not None:
                    comparable.append((sid, cell))
            if comparable:
                comparable.sort(key=lambda item: (item[1].gross, item[1].quote_line.pk))
                # Same qty/unit/currency/tax already gated in eligible
                best = comparable[0][1]
                for sid, cell in comparable:
                    if cell.gross == best.gross and cell.tax_basis == best.tax_basis:
                        cell.is_lowest = True
            rows.append(row)
        return {"rows": rows, "suppliers": suppliers}

    @classmethod
    @transaction.atomic
    def award_pr_lines(
        cls,
        pr: PurchaseRequest,
        selections: list[dict],
        *,
        actor=None,
        reason: str = "",
    ) -> list[PRLineAward]:
        if actor is not None:
            ProcurementService.assert_can_edit_procurement(actor)
        locked = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
        ProcurementService.require(
            locked.status in {PRStatus.APPROVED, PRStatus.ORDERED},
            "Yalnız təsdiqlənmiş PR üçün mükafat.",
        )
        if not selections:
            raise DomainError("Ən azı bir sətir seçilməlidir.")

        awards: list[PRLineAward] = []
        # Track portions reserved in this transaction before they hit the DB sum.
        batch_free: dict[int, Decimal] = {}
        batch_offer: dict[int, Decimal] = {}
        for sel in selections:
            pr_line_id = int(sel["pr_line_id"])
            quote_line_id = int(sel["quote_line_id"])
            pr_line = PRLine.objects.select_for_update().get(pk=pr_line_id, pr=locked)
            # Lock quote line row only (no outer join) then reload relations.
            RFQQuoteLine.objects.select_for_update().only("id").get(pk=quote_line_id)
            quote_line = RFQQuoteLine.objects.select_related(
                "quote", "quote__supplier_party", "pr_line"
            ).get(pk=quote_line_id)
            if quote_line.pr_line_id != pr_line.pk:
                raise DomainError("Təklif sətri PR sətrinə aid deyil.")
            if quote_line.response_status != QuoteLineResponseStatus.QUOTED:
                raise DomainError("Cavabsız sətir mükafatlandırıla bilməz.")
            if pr_line.pk not in batch_free:
                batch_free[pr_line.pk] = ProcurementService.pr_line_free_to_allocate_qty(
                    pr_line
                )
            free = batch_free[pr_line.pk]
            if free <= 0:
                raise DomainError("PR sətrində sərbəst (ayrıla bilən) miqdar yoxdur.")
            if "qty" in sel and sel["qty"] is not None and str(sel["qty"]).strip() != "":
                take = _quantize_qty(sel["qty"])
            else:
                take = free
            if take <= 0:
                raise DomainError("Mükafat miqdarı müsbət olmalıdır.")
            if take > free:
                raise DomainError(
                    f"Sərbəst miqdardan artıq mükafat "
                    f"(sərbəst {format(free, 'f')}, tələb {format(take, 'f')})."
                )
            quoted_qty = Decimal(str(quote_line.qty or 0))
            if quote_line.pk not in batch_offer:
                already = ProcurementService.quote_line_awarded_qty(quote_line)
                batch_offer[quote_line.pk] = quoted_qty - already
            offer_left = batch_offer[quote_line.pk]
            if take > offer_left:
                raise DomainError(
                    "Təklif olunan miqdardan artıq seçilə bilməz "
                    f"(qalan təklif {format(offer_left, 'f')}, seçim {format(take, 'f')})."
                )
            if (quote_line.unit or "") != (pr_line.unit or ""):
                raise DomainError("Vahid uyğun gəlmir.")
            if (quote_line.currency or "").upper() != _SUPPORTED_CURRENCY:
                raise DomainError("Yalnız AZN mükafatlandırıla bilər.")
            amounts = quote_line_amounts(quote_line)
            if amounts["tax_basis"] == "unknown":
                raise DomainError(
                    "Vergi bazası naməlumdur — Finance qaydası / Management öhdəliyi tələb olunur."
                )
            supplier = quote_line.quote.supplier_party
            existing = (
                PRLineAward.objects.select_for_update()
                .filter(
                    pr_line=pr_line,
                    supplier_party=supplier,
                    is_active=True,
                    po_line__isnull=True,
                )
                .first()
            )
            if existing is not None:
                raise DomainError(
                    "Bu podratçı üçün bu sətirdə artıq aktiv mükafat var — "
                    "əvvəlcə buraxın və ya PO-ya çevirin."
                )

            award = PRLineAward.objects.create(
                pr=locked,
                pr_line=pr_line,
                quote_line=quote_line,
                supplier_party=supplier,
                qty=take,
                unit_price=quote_line.unit_price,
                currency=quote_line.currency,
                vat_rate=quote_line.vat_rate,
                price_includes_vat=quote_line.price_includes_vat,
                reason=(sel.get("reason") or reason or "")[:255],
                actor=actor,
                is_active=True,
            )
            batch_free[pr_line.pk] = free - take
            batch_offer[quote_line.pk] = offer_left - take
            awards.append(award)
        return awards

    @classmethod
    def award_commitment_fingerprint(cls, awards: list[PRLineAward]) -> str:
        rows = []
        for a in sorted(awards, key=lambda x: x.pr_line_id):
            rows.append(
                {
                    "pr_line_id": a.pr_line_id,
                    "quote_line_id": a.quote_line_id,
                    "supplier_id": a.supplier_party_id,
                    "qty": format(Decimal(str(a.qty)), "f"),
                    "unit_price": format(_quantize_money(Decimal(str(a.unit_price))), "f"),
                    "currency": (a.currency or _SUPPORTED_CURRENCY).upper(),
                    "vat_rate": format(Decimal(str(a.vat_rate)), "f") if a.vat_rate is not None else "",
                    "price_includes_vat": bool(a.price_includes_vat),
                }
            )
        blob = json.dumps(
            {"awards": rows, "tax_basis": "per_line"},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:40]

    @classmethod
    def assess_awards_amount(cls, awards: list[PRLineAward]) -> AmountAssessment:
        if not awards:
            return AmountAssessment(None, "", "empty_request", "no_awards")
        total = Decimal("0")
        for a in awards:
            amounts = award_amounts(a)
            if amounts["tax_basis"] == "unknown" or amounts["gross"] is None:
                return AmountAssessment(
                    None, "", "amount_unknown", "award_tax_basis_unknown"
                )
            if (a.currency or "").upper() != _SUPPORTED_CURRENCY:
                return AmountAssessment(
                    None, a.currency, "currency_unsupported", "award_currency"
                )
            total += amounts["gross"]
        return AmountAssessment(
            _quantize_money(total),
            _SUPPORTED_CURRENCY,
            "ok",
            "rfq_quote_lines_gross",
        )

    @classmethod
    def create_pos_from_awards(
        cls,
        pr: PurchaseRequest,
        *,
        actor=None,
        supplier_ids: list[int] | None = None,
    ) -> list[SupplierPOOutcome]:
        if actor is not None:
            ProcurementService.assert_can_edit_procurement(actor)

        outcomes: list[SupplierPOOutcome] = []
        with transaction.atomic():
            locked = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
            awards_qs = (
                PRLineAward.objects.select_for_update()
                .filter(pr=locked, is_active=True, po_line__isnull=True)
                .select_related(
                    "pr_line", "quote_line", "quote_line__quote", "supplier_party"
                )
            )
            if supplier_ids is not None:
                awards_qs = awards_qs.filter(supplier_party_id__in=supplier_ids)
            awards = list(awards_qs)
            if not awards:
                return [
                    SupplierPOOutcome(
                        supplier_id=0,
                        supplier_name="",
                        status="failed",
                        message="Aktiv mükafat / sifariş edilməmiş sətir yoxdur.",
                    )
                ]

            by_supplier: dict[int, list[PRLineAward]] = {}
            for a in awards:
                by_supplier.setdefault(a.supplier_party_id, []).append(a)

            for supplier_id, group in by_supplier.items():
                name = group[0].supplier_party.display_name
                if all(a.po_line_id for a in group):
                    outcomes.append(
                        SupplierPOOutcome(
                            supplier_id=supplier_id,
                            supplier_name=name,
                            status="skipped",
                            message="Bu mükafatlar artıq PO-ya bağlanıb.",
                        )
                    )
                    continue
                try:
                    with transaction.atomic():
                        outcome = cls._issue_po_for_supplier_awards(
                            locked, group, actor=actor
                        )
                    outcomes.append(outcome)
                except DomainError as exc:
                    msg = str(exc)
                    needs_fin = any(
                        k in msg.lower()
                        for k in ("limit", "öhdəlik", "management", "təsdiq")
                    )
                    if needs_fin:
                        # Persist commitment outside rolled-back savepoint
                        try:
                            cls.escalate_awards_commitment(
                                locked, group, actor=actor
                            )
                        except DomainError:
                            pass
                        outcomes.append(
                            SupplierPOOutcome(
                                supplier_id=supplier_id,
                                supplier_name=name,
                                status="awaiting_financial_approval",
                                message=msg,
                            )
                        )
                    else:
                        outcomes.append(
                            SupplierPOOutcome(
                                supplier_id=supplier_id,
                                supplier_name=name,
                                status="failed",
                                message=msg,
                            )
                        )
        return outcomes

    @classmethod
    @transaction.atomic
    def escalate_awards_commitment(
        cls,
        pr: PurchaseRequest,
        awards: list[PRLineAward],
        *,
        actor=None,
        reason: str = "over_limit",
    ):
        """Idempotent Management commitment for a supplier's award set (survives issue rollback)."""
        from apps.workflows.services import ApprovalService

        assessed = cls.assess_awards_amount(awards)
        if not assessed.is_known:
            raise DomainError(
                ProcurementService._escalation_message(
                    assessed.reason or "amount_unknown"
                )
            )
        from apps.workflows.models import ApprovalStatus

        fingerprint = cls.award_commitment_fingerprint(awards)
        existing = ProcurementService.find_matching_commitment(
            pr, fingerprint=fingerprint, status=ApprovalStatus.PENDING
        )
        if existing is not None:
            return existing

        supplier = awards[0].supplier_party
        limit = ProcurementService.approval_limit_for(actor)
        return ApprovalService.request(
            workflow_code=WF_PROCUREMENT_COMMITMENT,
            requested_by=actor,
            entity=pr,
            payload={
                "pr_id": pr.pk,
                "code": pr.code,
                "supplier_id": supplier.pk,
                "quote_id": awards[0].quote_line.quote_id,
                "unit_price": format(
                    _quantize_money(Decimal(str(awards[0].unit_price))), "f"
                ),
                "amount": str(assessed.amount),
                "currency": assessed.currency,
                "amount_basis": "rfq_quote_lines_gross",
                "decision_scope": "process_and_amount",
                "tax_basis": "per_line",
                "fingerprint": fingerprint,
                "award_ids": [a.pk for a in awards],
                "lines": [
                    {
                        "pr_line_id": a.pr_line_id,
                        "quote_line_id": a.quote_line_id,
                        "qty": format(Decimal(str(a.qty)), "f"),
                        "unit_price": format(
                            _quantize_money(Decimal(str(a.unit_price))), "f"
                        ),
                        "vat_rate": format(Decimal(str(a.vat_rate)), "f")
                        if a.vat_rate is not None
                        else "",
                        "price_includes_vat": a.price_includes_vat,
                    }
                    for a in awards
                ],
                "escalation_reason": reason,
                "limit_amount": str(limit.max_amount) if limit else "",
                "limit_currency": _SUPPORTED_CURRENCY if limit else "",
                "source": pr.source,
            },
        )

    @classmethod
    def _issue_po_for_supplier_awards(
        cls,
        pr: PurchaseRequest,
        awards: list[PRLineAward],
        *,
        actor=None,
    ) -> SupplierPOOutcome:
        from apps.audit.services import log_action
        from apps.parties.models import PartyRoleCode
        from apps.workflows.models import ApprovalRequest, ApprovalStatus

        supplier = awards[0].supplier_party
        name = supplier.display_name
        if not supplier.roles.filter(role=PartyRoleCode.SUPPLIER).exists():
            raise DomainError("Seçilmiş party podratçı deyil.")

        assessed = cls.assess_awards_amount(awards)
        fingerprint = cls.award_commitment_fingerprint(awards)

        if not assessed.is_known:
            raise DomainError(
                ProcurementService._escalation_message(
                    assessed.reason or "amount_unknown"
                )
            )

        # Exact award-terms commitment required — no Admin / amount self-authorization.
        # Split orders: each supplier's independently approved commitment may proceed.
        commitment = ProcurementService.find_matching_commitment(
            pr, fingerprint=fingerprint, status=ApprovalStatus.APPROVED
        )
        if commitment is None:
            raise DomainError(
                ProcurementService._escalation_message("over_limit")
            )

        ceiling = ProcurementService.verified_spending_ceiling(commitment.payload)
        if ceiling is not None and assessed.amount > ceiling:
            raise DomainError(
                f"Təsdiq olunmuş öhdəlik limiti aşılır "
                f"({assessed.amount} > {ceiling} AZN)."
            )
        if (commitment.payload or {}).get("fingerprint") != fingerprint:
            raise DomainError(
                "Təsdiqlənmiş təklif şərtləri dəyişib — yeni Management təsdiqi tələb olunur."
            )
        # Consume awards atomically: reserved unissued qty becomes ordered PO qty.
        for a in awards:
            locked_award = PRLineAward.objects.select_for_update().get(pk=a.pk)
            if not locked_award.is_active or locked_award.po_line_id:
                raise DomainError("Mükafat artıq PO sətrinə bağlanıb və ya buraxılıb.")
            pr_line = PRLine.objects.select_for_update().get(pk=locked_award.pr_line_id)
            ordered = ProcurementService.pr_line_ordered_qty(pr_line)
            other_unissued = (
                ProcurementService.pr_line_awarded_unissued_qty(pr_line)
                - Decimal(str(locked_award.qty))
            )
            if other_unissued < 0:
                other_unissued = Decimal("0")
            if ordered + other_unissued + Decimal(str(locked_award.qty)) > Decimal(
                str(pr_line.qty or 0)
            ):
                raise DomainError(
                    f"Sətir {pr_line.pk} üçün kifayət qədər qalan miqdar yoxdur."
                )
            a.pk = locked_award.pk  # ensure freshest for later link

        from apps.procurement.services import _next_code

        po = PurchaseOrder.objects.create(
            code=_next_code("PO", PurchaseOrder),
            supplier_party=supplier,
            status=POStatus.SENT,
            pr=pr,
            ordered_at=timezone.localdate(),
        )
        for a in awards:
            locked_award = PRLineAward.objects.select_for_update().get(pk=a.pk)
            po_line = POLine.objects.create(
                po=po,
                description=locked_award.pr_line.description,
                sku=locked_award.pr_line.sku,
                qty=locked_award.qty,
                unit_price=locked_award.unit_price,
                pr_line=locked_award.pr_line,
                quote_line=locked_award.quote_line,
            )
            locked_award.po_line = po_line
            locked_award.save(update_fields=["po_line"])
            a.po_line = po_line

        if pr.status == PRStatus.APPROVED:
            pr.status = PRStatus.ORDERED
            pr.save(update_fields=["status"])

        if commitment is not None:
            locked_c = ApprovalRequest.objects.select_for_update().get(pk=commitment.pk)
            payload = dict(locked_c.payload or {})
            if not payload.get("consumed_po_id"):
                payload["consumed_po_id"] = po.pk
                locked_c.payload = payload
                locked_c.save(update_fields=["payload", "updated_at"])

        log_action(
            action="procurement.po.create_from_awards",
            actor=actor,
            entity=po,
            new_values={
                "code": po.code,
                "pr": pr.code,
                "supplier": str(supplier),
                "award_ids": [a.pk for a in awards],
            },
        )
        return SupplierPOOutcome(
            supplier_id=supplier.pk,
            supplier_name=name,
            status="issued",
            message=f"PO {po.code}",
            po=po,
            commitment_id=commitment.pk if commitment else None,
        )


# Register line-quote basis as verified monetary basis for ceilings
VERIFIED_MONETARY_BASES_LINE = frozenset(
    set(VERIFIED_MONETARY_BASES) | {"rfq_quote_lines_gross"}
)
