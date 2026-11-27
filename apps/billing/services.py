from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Charge, ChargeSource, Invoice, InvoiceLine, InvoiceStatus, Payment
from apps.billing.policy import apply_manual_penalty_amount, due_date_for, vat_amount, vat_breakdown
from apps.core import events as bus
from apps.core.services import DomainError


def next_invoice_code():
    """Allocate next INV-* code under row lock (call inside transaction.atomic)."""
    latest = (
        Invoice.objects.select_for_update()
        .filter(code__startswith="INV-")
        .order_by("-pk")
        .values_list("code", flat=True)
        .first()
    )
    nxt = 1001
    if latest:
        try:
            nxt = int(str(latest).split("-", 1)[1]) + 1
        except (IndexError, ValueError):
            codes = Invoice.objects.filter(code__startswith="INV-").values_list("code", flat=True)
            numbers = []
            for code in codes:
                try:
                    numbers.append(int(str(code).split("-", 1)[1]))
                except (IndexError, ValueError):
                    continue
            nxt = (max(numbers) + 1) if numbers else 1001
    return f"INV-{nxt}"


@transaction.atomic
def generate_invoice_from_charges(party, charge_ids, *, apply_vat: bool = True) -> Invoice:
    """Create DRAFT invoice (A.5 — accountant confirms later).

    Phase 4.3: deposit charges must not mix with rent/service/other on one invoice.
    """
    # Lock in pk order to avoid deadlocks when two operators invoice overlapping sets.
    charges = list(
        Charge.objects.select_for_update()
        .filter(
            party=party,
            pk__in=list(charge_ids),
            invoice__isnull=True,
        )
        .order_by("pk")
    )
    if not charges:
        raise ValueError("No uninvoiced charges found for party")

    sources = {c.source for c in charges}
    has_deposit = ChargeSource.DEPOSIT in sources
    has_other = bool(sources - {ChargeSource.DEPOSIT})
    if has_deposit and has_other:
        raise DomainError(
            "Depozit ayrıca fakturalanmalıdır — kirayə/xidmət sətirləri ilə qarışdırıla bilməz."
        )

    net = sum((c.amount or Decimal("0") for c in charges), Decimal("0"))
    vat = vat_amount(net) if apply_vat else Decimal("0")
    total = net + vat
    currency = charges[0].currency or "AZN"
    lease = next((c.lease for c in charges if c.lease_id), None)
    issue = timezone.localdate()

    # Lock invoice table slice before allocating code (concurrency).
    Invoice.objects.select_for_update().filter(code__startswith="INV-").order_by("-pk")[:1]
    invoice = Invoice.objects.create(
        code=next_invoice_code(),
        party=party,
        lease=lease,
        status=InvoiceStatus.DRAFT,
        issue_date=issue,
        due_date=due_date_for(issue),
        currency=currency,
        total=total,
    )
    lines = []
    for charge in charges:
        lines.append(
            InvoiceLine(
                invoice=invoice,
                charge=charge,
                description=charge.description,
                amount=charge.amount,
            )
        )
        charge.invoice = invoice
    if vat > 0:
        lines.append(
            InvoiceLine(
                invoice=invoice,
                charge=None,
                description="ƏDV 18%",
                amount=vat,
            )
        )
    InvoiceLine.objects.bulk_create(lines)
    Charge.objects.bulk_update(charges, ["invoice"])
    bus.emit(
        bus.INVOICE_GENERATED,
        payload={"invoice_id": invoice.pk, "code": invoice.code, "entity_model": "invoice"},
        event_key=f"invoice.generated.{invoice.pk}",
    )
    return invoice


@transaction.atomic
def confirm_invoice(invoice: Invoice, *, actor=None) -> Invoice:
    """DRAFT → ISSUED; create unposted JE."""
    if invoice.status != InvoiceStatus.DRAFT:
        raise DomainError("Yalnız draft faktura təsdiqlənə bilər.")
    issue = timezone.localdate()
    invoice.status = InvoiceStatus.ISSUED
    invoice.issue_date = issue
    invoice.due_date = due_date_for(issue)
    invoice.save(update_fields=["status", "issue_date", "due_date"])
    # Net = total - VAT line
    vat_lines = [ln for ln in invoice.lines.all() if (ln.description or "").startswith("ƏDV")]
    vat = sum((ln.amount for ln in vat_lines), Decimal("0"))
    net = (invoice.total or Decimal("0")) - vat
    from apps.accounting.services import AccountingService

    try:
        AccountingService.journal_from_invoice(invoice, net=net, vat=vat, posted=False)
    except DomainError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DomainError(f"Mühasibat jurnalı yaradılmadı: {exc}") from exc
    return invoice


WF_PAYMENT = "finance.payment"


def _assert_payment_approval(*, invoice: Invoice, amount, approval_request) -> tuple:
    """Load + validate APPROVED unconsumed finance.payment ApprovalRequest (row-locked)."""
    from django.contrib.contenttypes.models import ContentType

    from apps.workflows.models import ApprovalRequest, ApprovalStatus

    if approval_request is None:
        raise DomainError("Ödəniş üçün təsdiqlənmiş approval tələb olunur.")
    req_id = getattr(approval_request, "pk", approval_request)
    req = ApprovalRequest.objects.select_for_update().get(pk=req_id)
    payload = dict(req.payload or {})

    # Idempotent replay of consumed approval
    existing_pid = payload.get("payment_id")
    if existing_pid:
        existing = Payment.objects.filter(pk=existing_pid, invoice_id=invoice.pk).first()
        if existing is not None:
            return req, payload, existing
        raise DomainError("Bu approval artıq istehlak olunub, lakin ödəniş tapılmadı.")

    if req.workflow_code != WF_PAYMENT:
        raise DomainError("Yalnız finance.payment approval ilə ödəniş qeydə alınır.")
    if req.status != ApprovalStatus.APPROVED:
        raise DomainError("Ödəniş yalnız təsdiqlənmiş (APPROVED) sorğu ilə mümkündür.")
    if not req.decided_by_id:
        raise DomainError("Approval qərarı (decided_by) tələb olunur.")

    try:
        payload_invoice_id = int(payload.get("invoice_id"))
    except (TypeError, ValueError):
        raise DomainError("Approval-da invoice_id yoxdur.") from None
    if payload_invoice_id != invoice.pk:
        raise DomainError("Approval başqa fakturaya aiddir.")

    if req.entity_id is not None and req.entity_type_id is not None:
        inv_ct = ContentType.objects.get_for_model(Invoice)
        if req.entity_type_id != inv_ct.id or int(req.entity_id) != invoice.pk:
            raise DomainError("Approval entity faktura ilə uyğun gəlmir.")

    approved_amt = Decimal(str(payload.get("amount") or 0)).quantize(Decimal("0.01"))
    amt = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
    if abs(approved_amt - amt) > Decimal("0.01"):
        raise DomainError("Ödəniş məbləği təsdiqlənmiş məbləğlə uyğun gəlmir.")

    return req, payload, None


@transaction.atomic
def record_payment(
    *,
    invoice: Invoice,
    amount,
    approval_request,
    method: str = "bank",
    reference: str = "",
) -> Payment:
    """Apply payment only after a persisted APPROVED finance.payment ApprovalRequest.

    Locks Invoice + ApprovalRequest, validates binding, creates Payment, consumes approval
    (payload.payment_id) in one atomic transaction. Replay of the same approval is idempotent.
    """
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    req, payload, existing = _assert_payment_approval(
        invoice=invoice, amount=amount, approval_request=approval_request
    )
    if existing is not None:
        return existing

    pay_method = method or payload.get("method") or "bank"
    pay_ref = reference if reference is not None else (payload.get("reference") or "")
    payment = _apply_payment_locked(
        invoice=invoice,
        amount=amount,
        method=pay_method,
        reference=pay_ref,
        approval_id=req.pk,
    )
    payload["payment_id"] = payment.pk
    payload["consumed_at"] = timezone.now().isoformat()
    req.payload = payload
    req.save(update_fields=["payload", "updated_at"])
    return payment


def _apply_payment_locked(
    *, invoice: Invoice, amount, method: str, reference: str, approval_id=None
) -> Payment:
    """Create Payment + status + event + unposted JE. Caller holds the Invoice row lock
    inside ``transaction.atomic`` and has already authorised the payment."""
    if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE, InvoiceStatus.PAID):
        raise DomainError("Ödəniş yalnız təsdiqlənmiş faktura üçün.")
    if invoice.status == InvoiceStatus.VOID:
        raise DomainError("Ləğv olunmuş fakturaya ödəniş olmaz.")
    amt = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
    if amt <= 0:
        raise DomainError("Ödəniş məbləği müsbət olmalıdır.")
    bal = invoice_balance(invoice)
    if amt > bal + Decimal("0.01"):
        raise DomainError("Ödəniş qalıqdan böyük ola bilməz.")

    pay_method = method or "bank"
    pay_ref = reference or ""
    payment = Payment.objects.create(
        invoice=invoice,
        party=invoice.party,
        amount=amt,
        currency=invoice.currency or "AZN",
        method=pay_method,
        reference=pay_ref or "",
    )

    paid = sum((p.amount for p in invoice.payments.all()), Decimal("0"))
    if paid >= (invoice.total or 0):
        invoice.status = InvoiceStatus.PAID
        invoice.save(update_fields=["status"])
    bus.emit(
        bus.PAYMENT_RECEIVED,
        payload={
            "payment_id": payment.pk,
            "invoice_id": invoice.pk,
            "party_id": invoice.party_id,
            "amount": str(amt),
            "reference": pay_ref or "",
            "approval_id": approval_id,
            "entity_model": "payment",
        },
        event_key=f"payment.received.{payment.pk}",
    )
    from apps.accounting.services import AccountingService

    try:
        AccountingService.journal_from_payment(payment, posted=False)
    except DomainError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DomainError(f"Ödəniş jurnalı yaradılmadı: {exc}") from exc
    return payment


@transaction.atomic
def record_incoming_payment_verified(
    *,
    invoice: Invoice,
    amount,
    actor,
    method: str = "bank",
    reference: str = "",
    evidence=None,
) -> Payment:
    """Finance-verified INCOMING (resident → City Point) payment — no Management approval.

    Decision 04/05 prep. Scope is strictly the receivable ``Invoice``: supplier / outgoing payments
    stay on ``SupplierInvoiceService`` + Management approval, and ``record_payment`` keeps its
    mandatory APPROVED ``finance.payment`` request.

    * Only the Accountant may call it (``can_mutate_finance``).
    * Optional ``evidence`` (InvoicePaymentEvidence) is linked in the same transaction; replaying a
      call for an already-linked evidence returns the linked Payment (never a second Payment/JE).
    * A legacy PENDING ``finance.payment`` request for the same invoice and amount is cancelled so
      Management cannot later approve it and double-post the same cash.
    """
    from apps.finance.access import can_mutate_finance

    if not can_mutate_finance(actor):
        raise DomainError("Daxil olan ödənişi yalnız mühasib təsdiqləyə bilər.")

    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)

    if evidence is not None:
        from apps.billing.evidence_models import EvidenceStatus, InvoicePaymentEvidence

        evidence = InvoicePaymentEvidence.objects.select_for_update().get(pk=evidence.pk)
        if evidence.invoice_id != invoice.pk:
            raise DomainError("Sübut başqa fakturaya aiddir.")
        if evidence.status == EvidenceStatus.LINKED and evidence.payment_id:
            return evidence.payment
        if evidence.status == EvidenceStatus.CANCELLED:
            raise DomainError("Ləğv edilmiş sübut ödənişə bağlana bilməz.")

    payment = _apply_payment_locked(
        invoice=invoice,
        amount=amount,
        method=method or "bank",
        reference=reference or "",
        approval_id=None,
    )

    from apps.workflows.models import ApprovalRequest, ApprovalStatus
    from apps.workflows.services import ApprovalService

    pending = ApprovalRequest.objects.select_for_update().filter(
        workflow_code=WF_PAYMENT,
        status=ApprovalStatus.PENDING,
        payload__invoice_id=invoice.pk,
    )
    for legacy in list(pending):
        try:
            legacy_amt = Decimal(str((legacy.payload or {}).get("amount") or 0)).quantize(
                Decimal("0.01")
            )
        except Exception:  # noqa: BLE001
            continue
        if legacy_amt != payment.amount:
            continue
        ApprovalService.cancel(
            legacy,
            actor=actor,
            comment="Mühasib ödənişi təsdiqlədi — köhnə approval sorğusu ləğv edildi.",
        )

    if evidence is not None:
        from apps.billing.evidence_services import link_evidence_to_payment

        link_evidence_to_payment(evidence, payment, actor)
    return payment


@transaction.atomic
def void_invoice(invoice: Invoice, *, actor=None) -> Invoice:
    """DRAFT/ISSUED → VOID; unlink uninvoiced charges; reverse unposted/posted JE."""
    if invoice.status == InvoiceStatus.VOID:
        return invoice
    if invoice.status == InvoiceStatus.PAID or invoice.payments.exists():
        raise DomainError("Ödənişi olan faktura ləğv edilə bilməz.")
    if invoice.status not in (InvoiceStatus.DRAFT, InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE):
        raise DomainError("Bu statusda ləğv mümkün deyil.")
    from apps.accounting.models import JournalEntry
    from apps.accounting.services import AccountingService

    je = JournalEntry.objects.filter(source="billing.invoice", source_ref=f"invoice:{invoice.pk}").first()
    if je and not je.reversed_entry_id:
        AccountingService.reverse_journal(je, actor=actor, memo=f"Void {invoice.code}")

    Charge.objects.filter(invoice=invoice).update(invoice=None)
    invoice.status = InvoiceStatus.VOID
    invoice.save(update_fields=["status"])
    return invoice


def mark_overdue_invoices(*, as_of=None) -> int:
    as_of = as_of or timezone.localdate()
    qs = Invoice.objects.filter(
        status=InvoiceStatus.ISSUED,
        due_date__lt=as_of,
    )
    return qs.update(status=InvoiceStatus.OVERDUE)


@transaction.atomic
def apply_penalty_charge(invoice: Invoice, *, amount, description: str = "") -> Charge:
    """Manual penalty by accountant (A.5) — no auto formula."""
    amt = apply_manual_penalty_amount(amount)
    if amt <= 0:
        raise DomainError("Cərimə məbləği müsbət olmalıdır.")
    if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE, InvoiceStatus.DRAFT):
        raise DomainError("Bu faktura üçün cərimə tətbiq olunmur.")
    as_of = timezone.localdate()
    period_start = as_of.replace(day=1)
    label = description.strip() or f"Cərimə {invoice.code}"
    return Charge.objects.create(
        party=invoice.party,
        lease=invoice.lease,
        source=ChargeSource.PENALTY,
        description=label,
        amount=amt,
        currency=invoice.currency or "AZN",
        period_start=period_start,
        period_end=as_of,
    )


def invoice_balance(invoice: Invoice) -> Decimal:
    paid = sum((p.amount for p in invoice.payments.all()), Decimal("0"))
    return (invoice.total or Decimal("0")) - paid


def invoice_balance_as_of(invoice: Invoice, as_of) -> Decimal:
    """Operational balance reconstructed by issue_date / paid_at (Asia/Baku dates).

    DRAFT/VOID → 0. Payments counted only when paid_at <= as_of.
    """
    if invoice.status == InvoiceStatus.VOID:
        return Decimal("0")
    if invoice.status == InvoiceStatus.DRAFT:
        return Decimal("0")
    if not invoice.issue_date or invoice.issue_date > as_of:
        return Decimal("0")
    paid = sum(
        (p.amount or Decimal("0") for p in invoice.payments.all() if p.paid_at and p.paid_at <= as_of),
        Decimal("0"),
    )
    return (invoice.total or Decimal("0")) - paid


def invoice_vat_summary(invoice: Invoice) -> dict:
    vat = sum(
        (ln.amount for ln in invoice.lines.all() if (ln.description or "").startswith("ƏDV")),
        Decimal("0"),
    )
    net = (invoice.total or Decimal("0")) - vat
    return vat_breakdown(net) if vat == 0 and invoice.total else {
        "net": net,
        "vat": vat,
        "gross": invoice.total or Decimal("0"),
    }


def ar_aging_buckets(*, as_of=None):
    """Return open invoices grouped by aging bucket."""
    as_of = as_of or timezone.localdate()
    mark_overdue_invoices(as_of=as_of)
    open_statuses = (InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE)
    buckets = {
        "current": [],
        "1_30": [],
        "31_60": [],
        "61_90": [],
        "90_plus": [],
    }
    for inv in Invoice.objects.filter(status__in=open_statuses).select_related("party"):
        bal = invoice_balance(inv)
        if bal <= 0:
            continue
        due = inv.due_date or inv.issue_date or as_of
        days = (as_of - due).days
        row = {"invoice": inv, "balance": bal, "days_overdue": max(days, 0)}
        if days <= 0:
            buckets["current"].append(row)
        elif days <= 30:
            buckets["1_30"].append(row)
        elif days <= 60:
            buckets["31_60"].append(row)
        elif days <= 90:
            buckets["61_90"].append(row)
        else:
            buckets["90_plus"].append(row)
    return buckets
