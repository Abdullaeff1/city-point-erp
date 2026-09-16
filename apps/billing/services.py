from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Charge, Invoice, InvoiceLine, InvoiceStatus


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
    return invoice
