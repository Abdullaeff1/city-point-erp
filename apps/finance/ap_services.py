"""Supplier invoice capture, match/HOLD, recognition, void, and AP settlement."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.coa import code_for
from apps.accounting.models import Account
from apps.accounting.services import AccountingService, seed_minimal_coa
from apps.billing.models import (
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierInvoiceStatus,
    SupplierPayment,
)
from apps.core.services import DomainError, Service
from apps.procurement.models import POLine

RESERVING_STATUSES = (
    SupplierInvoiceStatus.MATCHED,
    SupplierInvoiceStatus.RECOGNIZED,
)

WF_SUPPLIER_PAYMENT = "finance.supplier_payment"

POSTED_VOID_BLOCKED = (
    "Posted AP faktura void/miqdar buraxılışı Finance təsdiqi tələb edir "
    "(posted JE reverse siyasəti hələ açıqdır)."
)


def _q(val) -> Decimal:
    return Decimal(str(val or 0))


def next_supplier_invoice_code() -> str:
    latest = (
        SupplierInvoice.objects.filter(code__startswith="SIN-")
        .order_by("-pk")
        .values_list("code", flat=True)
        .first()
    )
    nxt = 1001
    if latest:
        try:
            nxt = int(str(latest).split("-", 1)[1]) + 1
        except (IndexError, ValueError):
            nxt = SupplierInvoice.objects.filter(code__startswith="SIN-").count() + 1001
    return f"SIN-{nxt}"


def reserved_qty_for_po_line(po_line_id: int, *, exclude_invoice_id: int | None = None) -> Decimal:
    qs = SupplierInvoiceLine.objects.filter(
        po_line_id=po_line_id,
        supplier_invoice__status__in=RESERVING_STATUSES,
    )
    if exclude_invoice_id:
        qs = qs.exclude(supplier_invoice_id=exclude_invoice_id)
    total = qs.aggregate(s=Sum("qty_invoiced"))["s"]
    return _q(total)


def available_qty_for_po_line(po_line: POLine, *, exclude_invoice_id: int | None = None) -> Decimal:
    received = _q(po_line.received_qty)
    reserved = reserved_qty_for_po_line(po_line.pk, exclude_invoice_id=exclude_invoice_id)
    avail = received - reserved
    return avail if avail > 0 else Decimal("0")


def line_match_snapshot(line: SupplierInvoiceLine, *, exclude_invoice_id: int | None = None) -> dict:
    po_line = line.po_line
    excl = exclude_invoice_id if exclude_invoice_id is not None else line.supplier_invoice_id
    available = available_qty_for_po_line(po_line, exclude_invoice_id=excl)
    qty = _q(line.qty_invoiced)
    variance = qty - available
    return {
        "ordered": _q(po_line.qty),
        "received": _q(po_line.received_qty),
        "previously_reserved": reserved_qty_for_po_line(po_line.pk, exclude_invoice_id=excl),
        "available": available,
        "qty_invoiced": qty,
        "variance": variance,
        "over": variance > 0,
        "unit_price": _q(line.unit_price),
        "currency": line.supplier_invoice.currency,
        "tax_rate": _q(line.tax_rate),
        "line_net": line.line_net,
    }


def supplier_invoice_gross(invoice: SupplierInvoice) -> Decimal:
    total = Decimal("0.00")
    for ln in invoice.lines.all():
        total += ln.line_gross
    return total.quantize(Decimal("0.01"))


def payable_balance(invoice: SupplierInvoice) -> Decimal:
    """Operational open payable — drops when SupplierPayment rows exist (settlement)."""
    paid = invoice.payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")
    return (supplier_invoice_gross(invoice) - _q(paid)).quantize(Decimal("0.01"))


def posted_ap_balance(invoice: SupplierInvoice) -> Decimal:
    """Posted GL AP liability still open for this invoice (Cr − Dr on AP role account)."""
    from apps.accounting.models import JournalLine

    ap_code = code_for("ap")
    je_ids: list[int] = []
    if invoice.journal_entry_id:
        je_ids.append(invoice.journal_entry_id)
    je_ids.extend(
        list(
            invoice.payments.exclude(journal_entry_id=None).values_list(
                "journal_entry_id", flat=True
            )
        )
    )
    if not je_ids:
        return Decimal("0.00")
    agg = JournalLine.objects.filter(
        entry_id__in=je_ids,
        entry__posted=True,
        account__code=ap_code,
    ).aggregate(d=Sum("debit"), c=Sum("credit"))
    return (_q(agg["c"]) - _q(agg["d"])).quantize(Decimal("0.01"))


def open_payment_authorization_amount(invoice: SupplierInvoice) -> Decimal:
    """PENDING + APPROVED-but-unsettled authorizations (do not yet reduce payable_balance)."""
    from apps.workflows.models import ApprovalRequest, ApprovalStatus

    total = Decimal("0.00")
    qs = ApprovalRequest.objects.filter(
        workflow_code=WF_SUPPLIER_PAYMENT,
        status__in=(ApprovalStatus.PENDING, ApprovalStatus.APPROVED),
        payload__supplier_invoice_id=invoice.pk,
    )
    for req in qs:
        payload = req.payload or {}
        if payload.get("supplier_payment_id"):
            continue
        total += _q(payload.get("amount")).quantize(Decimal("0.01"))
    return total.quantize(Decimal("0.01"))


def authorizable_payable_amount(invoice: SupplierInvoice) -> Decimal:
    avail = payable_balance(invoice) - open_payment_authorization_amount(invoice)
    return avail if avail > 0 else Decimal("0.00")


def payable_recon_snapshot(invoice: SupplierInvoice) -> dict:
    """Explain ops vs posted AP from invoice JE + SupplierPayment rows."""
    gross = supplier_invoice_gross(invoice)
    ops = payable_balance(invoice)
    posted = posted_ap_balance(invoice)
    settled = (gross - ops).quantize(Decimal("0.01"))
    inv_je = invoice.journal_entry
    inv_posted = bool(inv_je and inv_je.posted)
    pay_rows = []
    for p in invoice.payments.select_related("journal_entry").all():
        je = p.journal_entry
        pay_rows.append(
            {
                "payment_id": p.pk,
                "amount": p.amount,
                "paid_at": p.paid_at,
                "reference": p.reference or "",
                "je_code": je.code if je else "",
                "je_posted": bool(je and je.posted),
            }
        )
    unposted_settle = sum(
        (_q(r["amount"]) for r in pay_rows if r["amount"] and not r["je_posted"]),
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    diff = (ops - posted).quantize(Decimal("0.01"))
    reasons = []
    if inv_je and not inv_posted:
        reasons.append(_("Faktura JE hələ post olunmayıb — posted AP 0 və ya natamam."))
    if unposted_settle > 0:
        reasons.append(
            _("Settlement JE unposted: %(amt)s — ops düşüb, posted AP hələ düşməyib.")
            % {"amt": unposted_settle}
        )
    if not reasons and diff == 0:
        reasons.append(_("Əməliyyat və posted AP uzlaşır."))
    elif not reasons and diff != 0:
        reasons.append(_("Fərq: ops − posted = %(diff)s — JE sətirlərini yoxlayın.") % {"diff": diff})
    return {
        "gross": gross,
        "settled": settled,
        "ops": ops,
        "posted": posted,
        "diff": diff,
        "invoice_je_posted": inv_posted,
        "unposted_settlement_amount": unposted_settle,
        "payments": pay_rows,
        "explanations": reasons,
    }


def supplier_payment_queue_invoice_ids(*, queue: str) -> list[int]:
    """Invoice PKs for payables queue chips (pending / awaiting_settle)."""
    from apps.workflows.models import ApprovalRequest, ApprovalStatus

    if queue == "pending_approval":
        qs = ApprovalRequest.objects.filter(
            workflow_code=WF_SUPPLIER_PAYMENT, status=ApprovalStatus.PENDING
        )
    elif queue == "awaiting_settle":
        qs = ApprovalRequest.objects.filter(
            workflow_code=WF_SUPPLIER_PAYMENT, status=ApprovalStatus.APPROVED
        )
    else:
        return []
    ids: list[int] = []
    for req in qs:
        payload = req.payload or {}
        if queue == "awaiting_settle" and payload.get("supplier_payment_id"):
            continue
        try:
            ids.append(int(payload.get("supplier_invoice_id")))
        except (TypeError, ValueError):
            continue
    return sorted(set(ids))


class SupplierInvoiceService(Service):
    @classmethod
    @transaction.atomic
    def create_draft(
        cls,
        *,
        supplier_party,
        supplier_invoice_no: str,
        invoice_date=None,
        currency: str = "AZN",
        notes: str = "",
        lines: list[dict],
        actor=None,
    ) -> SupplierInvoice:
        cls.require(supplier_party is not None, _("Podratçı seçilməlidir."))
        no = (supplier_invoice_no or "").strip()
        cls.require(bool(no), _("Podratçı faktura № tələb olunur."))
        if SupplierInvoice.objects.filter(
            supplier_party=supplier_party, supplier_invoice_no=no
        ).exists():
            raise DomainError(_("Bu podratçı üçün eyni faktura № artıq var."))
        cls.require(bool(lines), _("Ən azı bir sətir lazımdır."))
        inv = SupplierInvoice.objects.create(
            code=next_supplier_invoice_code(),
            supplier_party=supplier_party,
            supplier_invoice_no=no,
            invoice_date=invoice_date or timezone.localdate(),
            currency=(currency or "AZN").upper(),
            status=SupplierInvoiceStatus.DRAFT,
            notes=notes or "",
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
        for row in lines:
            po_line = row.get("po_line") or POLine.objects.get(pk=row["po_line_id"])
            qty = _q(row.get("qty_invoiced"))
            cls.require(qty > 0, _("Faktura miqdarı müsbət olmalıdır."))
            SupplierInvoiceLine.objects.create(
                supplier_invoice=inv,
                po_line=po_line,
                description=(row.get("description") or po_line.description or "")[:255],
                qty_invoiced=qty,
                unit_price=_q(row.get("unit_price", po_line.unit_price)),
                tax_rate=_q(row.get("tax_rate", 0)),
            )
        return inv

    @classmethod
    @transaction.atomic
    def validate_and_match_or_hold(cls, invoice: SupplierInvoice, *, actor=None) -> SupplierInvoice:
        """Keep supplier qty intact; HOLD whole doc if any line exceeds available."""
        inv = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        cls.require(
            inv.status in (SupplierInvoiceStatus.DRAFT, SupplierInvoiceStatus.HOLD),
            _("Yalnız draft/hold sənəd yoxlanıla bilər."),
        )
        lines = list(inv.lines.select_related("po_line").all())
        cls.require(bool(lines), _("Sətir yoxdur."))
        po_ids = sorted({ln.po_line_id for ln in lines})
        po_map = {
            p.pk: p
            for p in POLine.objects.select_for_update().filter(pk__in=po_ids).order_by("pk")
        }
        any_over = False
        for ln in lines:
            po_line = po_map[ln.po_line_id]
            available = _q(po_line.received_qty) - reserved_qty_for_po_line(
                po_line.pk, exclude_invoice_id=inv.pk
            )
            if available < 0:
                available = Decimal("0")
            variance = _q(ln.qty_invoiced) - available
            ln.variance_qty = variance
            ln.save(update_fields=["variance_qty"])
            if variance > 0:
                any_over = True

        if any_over:
            inv.status = SupplierInvoiceStatus.HOLD
            inv.hold_reason = _(
                "Faktura miqdarı qəbul/rezervdən artıqdır — sənəd HOLD; AP jurnal yaradılmır."
            )
            inv.save(update_fields=["status", "hold_reason", "updated_at"])
        else:
            inv.status = SupplierInvoiceStatus.MATCHED
            inv.hold_reason = ""
            inv.save(update_fields=["status", "hold_reason", "updated_at"])
        return inv

    @classmethod
    @transaction.atomic
    def revalidate_hold(cls, invoice: SupplierInvoice, *, actor=None) -> SupplierInvoice:
        inv = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        cls.require(inv.status == SupplierInvoiceStatus.HOLD, _("Yalnız HOLD sənəd yenidən yoxlanır."))
        inv.status = SupplierInvoiceStatus.DRAFT
        inv.save(update_fields=["status", "updated_at"])
        return cls.validate_and_match_or_hold(inv, actor=actor)

    @classmethod
    @transaction.atomic
    def void_supplier_invoice(cls, invoice: SupplierInvoice, *, actor=None) -> SupplierInvoice:
        """Void before recognition releases reservation.

        Recognized + unposted JE: reverse draft JE then void (releases reservation).
        Recognized + posted JE: blocked — Finance reverse policy pending; qty stays reserved.
        """
        inv = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        cls.require(inv.status != SupplierInvoiceStatus.VOID, _("Artıq void."))

        po_ids = list(inv.lines.values_list("po_line_id", flat=True))
        list(POLine.objects.select_for_update().filter(pk__in=po_ids).order_by("pk"))

        if inv.status == SupplierInvoiceStatus.RECOGNIZED:
            je = inv.journal_entry
            if je is not None:
                je = type(je).objects.select_for_update().get(pk=je.pk)
                if je.posted:
                    raise DomainError(_(POSTED_VOID_BLOCKED))
                # Unposted recognition JE — reverse then void (approved unposted reverse path).
                AccountingService.reverse_journal(
                    je, actor=actor, memo=f"Void {inv.code} (unposted reverse)"
                )
            if inv.payments.exists():
                raise DomainError(_("Ödənişi olan AP faktura void edilə bilməz."))
            inv.status = SupplierInvoiceStatus.VOID
            inv.hold_reason = ""
            inv.save(update_fields=["status", "hold_reason", "updated_at"])
            return inv

        # draft / hold / matched
        inv.status = SupplierInvoiceStatus.VOID
        inv.hold_reason = ""
        inv.save(update_fields=["status", "hold_reason", "updated_at"])
        return inv

    @classmethod
    def recognition_block_reason(cls, invoice: SupplierInvoice) -> str | None:
        if invoice.status != SupplierInvoiceStatus.MATCHED:
            return _("Yalnız MATCHED sənəd tanına bilər.")
        seed_minimal_coa()
        for role in ("ap", "expense"):
            code = code_for(role)
            if not Account.objects.filter(code=code, is_active=True).exists():
                return _(
                    "Tanıma mümkün deyil — CoA mapping/hesab yoxdur: rol=%(role)s kod=%(code)s."
                ) % {"role": role, "code": code}
        return None

    @classmethod
    @transaction.atomic
    def recognize_payable(cls, invoice: SupplierInvoice, *, actor=None) -> SupplierInvoice:
        inv = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        block = cls.recognition_block_reason(inv)
        if block:
            raise DomainError(block)
        lines = list(inv.lines.select_related("po_line"))
        po_ids = sorted({ln.po_line_id for ln in lines})
        po_map = {
            p.pk: p
            for p in POLine.objects.select_for_update().filter(pk__in=po_ids).order_by("pk")
        }
        for ln in lines:
            po_line = po_map[ln.po_line_id]
            available_including_self = _q(po_line.received_qty) - reserved_qty_for_po_line(
                po_line.pk, exclude_invoice_id=inv.pk
            )
            if _q(ln.qty_invoiced) > available_including_self:
                raise DomainError(
                    _("Miqdar artıq rezerv olunub və ya qəbul kifayət etmir (PO sətir %(id)s).")
                    % {"id": po_line.pk}
                )

        net = sum((ln.line_net for ln in lines), Decimal("0")).quantize(Decimal("0.01"))
        vat = sum((ln.line_vat for ln in lines), Decimal("0")).quantize(Decimal("0.01"))
        gross = (net + vat).quantize(Decimal("0.01"))
        je_lines = [
            {
                "account_code": code_for("expense"),
                "debit": net,
                "credit": 0,
                "memo": f"AP {inv.code}",
            },
            {
                "account_code": code_for("ap"),
                "debit": 0,
                "credit": gross,
                "memo": f"AP {inv.code}",
            },
        ]
        if vat > 0:
            je_lines.insert(
                1,
                {
                    "account_code": code_for("vat"),
                    "debit": vat,
                    "credit": 0,
                    "memo": f"VAT {inv.code}",
                },
            )

        entry = AccountingService.post_journal(
            lines=je_lines,
            memo=f"Supplier invoice {inv.code}",
            source="billing.supplier_invoice",
            source_ref=f"supplier_invoice:{inv.pk}",
            entry_date=inv.invoice_date or timezone.localdate(),
            actor=actor,
            posted=False,
        )
        inv.status = SupplierInvoiceStatus.RECOGNIZED
        inv.journal_entry = entry
        inv.save(update_fields=["status", "journal_entry", "updated_at"])
        return inv

    @classmethod
    @transaction.atomic
    def request_supplier_payment(
        cls,
        invoice: SupplierInvoice,
        *,
        amount,
        actor=None,
        method: str = "bank",
        reference: str = "",
    ):
        from apps.workflows.models import ApprovalRequest, ApprovalStatus
        from apps.workflows.services import ApprovalService

        inv = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        cls.require(
            inv.status == SupplierInvoiceStatus.RECOGNIZED,
            _("Ödəniş yalnız RECOGNIZED AP faktura üçün."),
        )
        amt = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
        cls.require(amt > 0, _("Məbləğ müsbət olmalıdır."))
        available = authorizable_payable_amount(inv)
        if amt > available:
            raise DomainError(
                _("Ödəniş açıq kreditor qalığından (təsdiq rezervləri çıxılmaqla) böyük ola bilməz.")
            )
        exists = ApprovalRequest.objects.filter(
            workflow_code=WF_SUPPLIER_PAYMENT,
            status=ApprovalStatus.PENDING,
            payload__supplier_invoice_id=inv.pk,
        ).exists()
        cls.require(not exists, _("Gözləyən podratçı ödəniş sorğusu artıq var."))
        return ApprovalService.request(
            workflow_code=WF_SUPPLIER_PAYMENT,
            requested_by=actor,
            entity=inv,
            payload={
                "supplier_invoice_id": inv.pk,
                "supplier_invoice_code": inv.code,
                "amount": str(amt),
                "method": method or "bank",
                "reference": reference or "",
                "currency": inv.currency or "AZN",
            },
        )

    @classmethod
    @transaction.atomic
    def record_supplier_payment(
        cls,
        *,
        invoice: SupplierInvoice,
        amount,
        approval_request,
        method: str = "bank",
        reference: str = "",
        paid_at=None,
    ) -> SupplierPayment:
        """Bank settlement after APPROVED finance.supplier_payment — creates SupplierPayment.

        Approval alone does not create SPAY or reduce operational payable.
        Settlement creates SPAY + unposted JE; payable_balance drops immediately;
        posted_ap_balance drops only after post_to_gl on the payment JE.
        """
        from apps.workflows.models import ApprovalRequest, ApprovalStatus

        inv = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        cls.require(
            inv.status == SupplierInvoiceStatus.RECOGNIZED,
            _("Ödəniş yalnız RECOGNIZED AP faktura üçün."),
        )
        req_id = getattr(approval_request, "pk", approval_request)
        req = ApprovalRequest.objects.select_for_update().get(pk=req_id)
        payload = dict(req.payload or {})

        existing_pid = payload.get("supplier_payment_id")
        if existing_pid:
            existing = SupplierPayment.objects.filter(
                pk=existing_pid, supplier_invoice_id=inv.pk
            ).first()
            if existing is not None:
                return existing
            raise DomainError(_("Bu approval artıq istehlak olunub, lakin ödəniş tapılmadı."))

        if req.workflow_code != WF_SUPPLIER_PAYMENT:
            raise DomainError(
                _("Yalnız finance.supplier_payment approval ilə podratçı ödənişi qeydə alınır.")
            )
        if req.status != ApprovalStatus.APPROVED:
            raise DomainError(_("Settlement yalnız APPROVED sorğu ilə mümkündür."))
        try:
            payload_inv = int(payload.get("supplier_invoice_id"))
        except (TypeError, ValueError) as exc:
            raise DomainError(_("Approval-da supplier_invoice_id yoxdur.")) from exc
        if payload_inv != inv.pk:
            raise DomainError(_("Approval başqa AP fakturaya aiddir."))

        amt = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
        approved_amt = Decimal(str(payload.get("amount") or 0)).quantize(Decimal("0.01"))
        if amt != approved_amt:
            raise DomainError(_("Ödəniş məbləği təsdiqlənmiş məbləğlə uyğun gəlmir."))
        if amt <= 0:
            raise DomainError(_("Ödəniş məbləği müsbət olmalıdır."))
        bal = payable_balance(inv)
        if amt > bal:
            raise DomainError(_("Ödəniş açıq kreditor qalığından böyük ola bilməz."))

        pay_method = method or payload.get("method") or "bank"
        # Settlement evidence: bank/transfer reference required (synthetic until bank feed).
        pay_ref = (reference if reference is not None else "") or ""
        pay_ref = pay_ref.strip() or (payload.get("reference") or "").strip()
        cls.require(
            bool(pay_ref),
            _("Settlement üçün bank/transfer reference (sübut) tələb olunur."),
        )
        # One bank trx ref → one SupplierPayment (duplicate settlement guard).
        # Multi-invoice single transfer = Finance decision pending — not supported yet.
        dup = SupplierPayment.objects.filter(reference__iexact=pay_ref).first()
        if dup is not None:
            raise DomainError(
                _(
                    "Bu bank reference artıq settlement-də istifadə olunub "
                    "(SPAY-%(pid)s / %(code)s). Eyni transferin bir neçə fakturaya "
                    "bölünməsi hələ təsdiqlənməyib."
                )
                % {"pid": dup.pk, "code": dup.supplier_invoice.code}
            )
        settle_date = paid_at or timezone.localdate()
        payment = SupplierPayment.objects.create(
            supplier_invoice=inv,
            amount=amt,
            currency=inv.currency or "AZN",
            method=pay_method,
            reference=pay_ref,
            paid_at=settle_date,
            approval_request=req,
        )
        cash_code = code_for("cash") if (pay_method or "").lower() == "cash" else code_for("bank")
        entry = AccountingService.post_journal(
            lines=[
                {
                    "account_code": code_for("ap"),
                    "debit": amt,
                    "credit": 0,
                    "memo": f"AP pay {inv.code}",
                },
                {
                    "account_code": cash_code,
                    "debit": 0,
                    "credit": amt,
                    "memo": f"AP pay {inv.code}",
                },
            ],
            memo=f"Supplier payment {inv.code}",
            source="billing.supplier_payment",
            source_ref=f"supplier_payment:{payment.pk}",
            entry_date=settle_date,
            actor=None,
            posted=False,
        )
        payment.journal_entry = entry
        payment.save(update_fields=["journal_entry"])
        payload["supplier_payment_id"] = payment.pk
        payload["settled_at"] = str(settle_date)
        payload["settlement_reference"] = pay_ref
        req.payload = payload
        req.save(update_fields=["payload", "updated_at"])
        return payment

    @classmethod
    @transaction.atomic
    def cancel_payment_authorization(
        cls,
        approval_request,
        *,
        actor=None,
        reason: str = "",
    ):
        """Abandon PENDING or APPROVED-unsettled AP payment auth; releases reserve.

        Settled approvals (supplier_payment_id set) cannot be cancelled here.
        """
        from apps.workflows.models import ApprovalRequest, ApprovalStatus

        req_id = getattr(approval_request, "pk", approval_request)
        req = ApprovalRequest.objects.select_for_update().get(pk=req_id)
        cls.require(
            req.workflow_code == WF_SUPPLIER_PAYMENT,
            _("Yalnız finance.supplier_payment ləğv edilə bilər."),
        )
        reason = (reason or "").strip()
        cls.require(bool(reason), _("Ləğv səbəbi tələb olunur."))
        payload = dict(req.payload or {})
        if payload.get("supplier_payment_id"):
            raise DomainError(
                _("Settlement artıq qeydə alınıb — approval ləğv edilə bilməz.")
            )
        if req.status == ApprovalStatus.PENDING:
            pass
        elif req.status == ApprovalStatus.APPROVED:
            pass
        else:
            raise DomainError(_("Yalnız gözləyən və ya təsdiqlənmiş-unsettled sorğu ləğv edilir."))

        req.status = ApprovalStatus.CANCELLED
        req.decided_by = actor if getattr(actor, "is_authenticated", False) else None
        req.decided_at = timezone.now()
        req.comment = reason[:2000]
        payload["cancelled_reason"] = reason[:500]
        req.payload = payload
        req.save(
            update_fields=[
                "status",
                "decided_by",
                "decided_at",
                "comment",
                "payload",
                "updated_at",
            ]
        )
        return req
