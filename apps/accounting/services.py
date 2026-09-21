"""Accounting journal posting (Phase 12 thin) + CoA seed."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounting.models import Account, AccountType, JournalEntry, JournalLine
from apps.core import events as bus
from apps.core.services import DomainError, Service


def seed_minimal_coa() -> int:
    rows = [
        ("1000", "Cash / Bank", AccountType.ASSET),
        ("1100", "Accounts Receivable", AccountType.ASSET),
        ("2000", "Accounts Payable", AccountType.LIABILITY),
        ("4000", "Rental Revenue", AccountType.REVENUE),
        ("4100", "Service Charge Revenue", AccountType.REVENUE),
        ("4200", "Other Income", AccountType.REVENUE),
    ]
    created = 0
    for code, name, atype in rows:
        _, was = Account.objects.get_or_create(code=code, defaults={"name": name, "account_type": atype})
        if was:
            created += 1
    return created


def _next_je_code() -> str:
    codes = JournalEntry.objects.filter(code__startswith="JE-").values_list("code", flat=True)
    numbers = []
    for code in codes:
        try:
            numbers.append(int(code.split("-")[1]))
        except (IndexError, ValueError):
            continue
    nxt = (max(numbers) + 1) if numbers else 1001
    return f"JE-{nxt}"


class AccountingService(Service):
    @classmethod
    @transaction.atomic
    def post_journal(
        cls,
        *,
        lines: list[dict],
        memo: str = "",
        source: str = "",
        entry_date=None,
    ) -> JournalEntry:
        """lines: [{account_code, debit, credit, memo?}] — debits must equal credits."""
        cls.require(len(lines) >= 2, "Ən azı 2 sətir lazımdır.")
        total_d = sum(Decimal(str(x.get("debit") or 0)) for x in lines)
        total_c = sum(Decimal(str(x.get("credit") or 0)) for x in lines)
        if total_d != total_c:
            raise DomainError("Debit və credit bərabər olmalıdır.")
        entry = JournalEntry.objects.create(
            code=_next_je_code(),
            entry_date=entry_date or timezone.localdate(),
            memo=memo or "",
            source=source or "",
            posted=True,
        )
        for row in lines:
            acct = Account.objects.get(code=row["account_code"])
            JournalLine.objects.create(
                entry=entry,
                account=acct,
                debit=Decimal(str(row.get("debit") or 0)),
                credit=Decimal(str(row.get("credit") or 0)),
                memo=row.get("memo") or "",
            )
        return entry

    @classmethod
    def journal_from_invoice(cls, invoice) -> JournalEntry:
        seed_minimal_coa()
        amount = invoice.total or Decimal("0")
        entry = cls.post_journal(
            memo=f"Invoice {invoice.code}",
            source="billing",
            lines=[
                {"account_code": "1100", "debit": amount, "credit": 0},
                {"account_code": "4000", "debit": 0, "credit": amount},
            ],
        )
        bus.emit(bus.INVOICE_GENERATED, payload={"invoice_id": invoice.pk, "code": invoice.code})
        return entry
