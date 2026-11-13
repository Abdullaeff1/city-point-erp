"""A.5 billing calendar (AZ business center) — updated decisions."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

# Invoice preparation window: days 1..INVOICE_WINDOW_DAYS of each month
INVOICE_WINDOW_DAYS = 5
# Due = issue + ~1 month
DUE_DAYS = 30
VAT_RATE = Decimal("0.18")


def due_date_for(issue_date: date | None = None) -> date:
    from django.utils import timezone

    day = issue_date or timezone.localdate()
    return day + timedelta(days=DUE_DAYS)


def in_invoice_window(as_of: date | None = None) -> bool:
    from django.utils import timezone

    as_of = as_of or timezone.localdate()
    return 1 <= as_of.day <= INVOICE_WINDOW_DAYS


def vat_amount(net: Decimal) -> Decimal:
    return (Decimal(net or 0) * VAT_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def vat_breakdown(net: Decimal) -> dict:
    n = Decimal(net or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    vat = vat_amount(n)
    return {"net": n, "vat": vat, "gross": n + vat}


def apply_manual_penalty_amount(amount) -> Decimal:
    """Accountant-entered penalty only (no auto formula)."""
    return Decimal(str(amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
