from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Charge, ChargeSource, Invoice, InvoiceLine, InvoiceStatus, Payment
from apps.billing.policy import apply_manual_penalty_amount, due_date_for, vat_amount, vat_breakdown
from apps.core import events as bus
from apps.core.services import DomainError


def next_invoice_code():
    codes = Invoice.objects.filter(code__startswith="INV-").values_list("code", flat=True)
    numbers = []
    for code in codes:
        try:
            numbers.append(int(code.split("-")[1]))
        except (IndexError, ValueError):
            continue
    nxt = (max(numbers) + 1) if numbers else 1001
    return f"INV-{nxt}"


@transaction.atomic
def generate_invoice_from_charges(party, charge_ids, *, apply_vat: bool = True) -> Invoice:
    """Create DRAFT invoice (A.5 — accountant confirms later)."""
    charges = list(
        Charge.objects.select_for_update().filter(
            party=party,
            pk__in=list(charge_ids),
            invoice__isnull=True,
        )
    )
    if not charges:
        raise ValueError("No uninvoiced charges found for party")

    net = sum((c.amount or Decimal("0") for c in charges), Decimal("0"))
    vat = vat_amount(net) if apply_vat else Decimal("0")
    total = net + vat
    currency = charges[0].currency or "AZN"
    lease = next((c.lease for c in charges if c.lease_id), None)
    issue = timezone.localdate()

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
    bus.emit(bus.INVOICE_GENERATED, payload={"invoice_id": invoice.pk, "code": invoice.code})
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
    try:
        from apps.accounting.services import AccountingService

        AccountingService.journal_from_invoice(invoice, net=net, vat=vat, posted=False)
    except Exception:
        pass
    return invoice


@transaction.atomic
def record_payment(*, invoice: Invoice, amount, method: str = "bank", reference: str = "") -> Payment:
    """Apply payment after management approval (caller enforces ACL)."""
    if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE, InvoiceStatus.PAID):
        raise DomainError("Ödəniş yalnız təsdiqlənmiş faktura üçün.")
    payment = Payment.objects.create(
        invoice=invoice,
        amount=amount,
        currency=invoice.currency or "AZN",
        method=method or "bank",
        reference=reference or "",
    )
    paid = sum((p.amount for p in invoice.payments.all()), Decimal("0"))
    if paid >= (invoice.total or 0):
        invoice.status = InvoiceStatus.PAID
        invoice.save(update_fields=["status"])
    bus.emit(
        bus.PAYMENT_RECEIVED,
        payload={"payment_id": payment.pk, "invoice_id": invoice.pk, "amount": str(amount)},
    )
    try:
        from apps.accounting.services import AccountingService

        AccountingService.journal_from_payment(payment, posted=False)
    except Exception:
        pass
    return payment


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
