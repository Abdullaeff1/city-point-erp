from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Charge, Invoice, InvoiceLine, InvoiceStatus, Payment
from apps.core import events as bus


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
def generate_invoice_from_charges(party, charge_ids) -> Invoice:
    charges = list(
        Charge.objects.select_for_update().filter(
            party=party,
            pk__in=list(charge_ids),
            invoice__isnull=True,
        )
    )
    if not charges:
        raise ValueError("No uninvoiced charges found for party")

    total = sum((c.amount or Decimal("0") for c in charges), Decimal("0"))
    currency = charges[0].currency or "AZN"
    lease = next((c.lease for c in charges if c.lease_id), None)

    invoice = Invoice.objects.create(
        code=next_invoice_code(),
        party=party,
        lease=lease,
        status=InvoiceStatus.ISSUED,
        issue_date=timezone.localdate(),
        due_date=timezone.localdate() + timedelta(days=14),
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
    InvoiceLine.objects.bulk_create(lines)
    Charge.objects.bulk_update(charges, ["invoice"])
    bus.emit(bus.INVOICE_GENERATED, payload={"invoice_id": invoice.pk, "code": invoice.code})
    try:
        from apps.accounting.services import AccountingService

        AccountingService.journal_from_invoice(invoice)
    except Exception:
        pass
    return invoice


@transaction.atomic
def record_payment(*, invoice: Invoice, amount, method: str = "bank", reference: str = "") -> Payment:
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
    return payment
