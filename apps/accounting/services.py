"""Accounting journal posting + CoA seed/import + period close + trial balance (A.6)."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from django.db import transaction
from django.utils import timezone

from apps.accounting.coa import DEFAULT_COA_ROWS, code_for
from apps.accounting.models import Account, AccountType, AccountingPeriod, JournalEntry, JournalLine
from apps.core.services import DomainError, Service

_TYPE_MAP = {
    "asset": AccountType.ASSET,
    "liability": AccountType.LIABILITY,
    "equity": AccountType.EQUITY,
    "revenue": AccountType.REVENUE,
    "expense": AccountType.EXPENSE,
    AccountType.ASSET: AccountType.ASSET,
    AccountType.LIABILITY: AccountType.LIABILITY,
    AccountType.EQUITY: AccountType.EQUITY,
    AccountType.REVENUE: AccountType.REVENUE,
    AccountType.EXPENSE: AccountType.EXPENSE,
}


def seed_minimal_coa() -> int:
    """3-digit placeholder CoA (cash + bank + AR/AP + revenue). Real plan via import."""
    created = 0
    for code, name, atype in DEFAULT_COA_ROWS:
        at = _TYPE_MAP.get(atype, AccountType.ASSET)
        obj, was = Account.objects.get_or_create(
            code=code, defaults={"name": name, "account_type": at}
        )
        if was:
            created += 1
        elif obj.name != name or obj.account_type != at:
            obj.name = name
            obj.account_type = at
            obj.save(update_fields=["name", "account_type"])
    return created


def import_coa_rows(rows: list[dict]) -> dict:
    """rows: [{code, name, account_type}] — 3-digit international."""
    created = updated = 0
    for row in rows:
        code = str(row.get("code") or "").strip()
        name = str(row.get("name") or "").strip()
        raw_type = str(row.get("account_type") or row.get("type") or "asset").strip().lower()
        if not code or not name:
            continue
        at = _TYPE_MAP.get(raw_type, AccountType.ASSET)
        obj, was = Account.objects.update_or_create(
            code=code,
            defaults={"name": name, "account_type": at, "is_active": True},
        )
        if was:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated}


def import_coa_from_xlsx(file_bytes: bytes) -> dict:
    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if not row or row[0] is None:
            continue
        if i == 0 and str(row[0]).lower() in ("code", "kod", "hesab"):
            continue
        rows.append(
            {
                "code": row[0],
                "name": row[1] if len(row) > 1 else "",
                "account_type": row[2] if len(row) > 2 else "asset",
            }
        )
    return import_coa_rows(rows)


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


def ensure_period(year: int, month: int) -> AccountingPeriod:
    period, _ = AccountingPeriod.objects.get_or_create(year=year, month=month)
    return period


def assert_period_open(entry_date) -> AccountingPeriod:
    period = ensure_period(entry_date.year, entry_date.month)
    if period.is_closed:
        raise DomainError(f"Dövr bağlıdır: {period}")
    return period


def trial_balance(*, year: int | None = None, month: int | None = None) -> list[dict]:
    """Sum posted journal lines only."""
    seed_minimal_coa()
    qs = JournalLine.objects.filter(entry__posted=True).select_related("account", "entry")
    if year and month:
        qs = qs.filter(entry__entry_date__year=year, entry__entry_date__month=month)
    elif year:
        qs = qs.filter(entry__entry_date__year=year)
    totals: dict[str, dict] = {}
    for line in qs:
        key = line.account.code
        bucket = totals.setdefault(
            key,
            {
                "code": line.account.code,
                "name": line.account.name,
                "account_type": line.account.account_type,
                "debit": Decimal("0"),
                "credit": Decimal("0"),
            },
        )
        bucket["debit"] += line.debit or Decimal("0")
        bucket["credit"] += line.credit or Decimal("0")
    rows = []
    for code in sorted(totals.keys()):
        row = totals[code]
        row["balance"] = row["debit"] - row["credit"]
        rows.append(row)
    return rows


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
        actor=None,
        posted: bool = False,
    ) -> JournalEntry:
        """lines: [{account_code, debit, credit, memo?}] — debits must equal credits."""
        cls.require(len(lines) >= 2, "Ən azı 2 sətir lazımdır.")
        entry_date = entry_date or timezone.localdate()
        assert_period_open(entry_date)
        total_d = sum(Decimal(str(x.get("debit") or 0)) for x in lines)
        total_c = sum(Decimal(str(x.get("credit") or 0)) for x in lines)
        if total_d != total_c:
            raise DomainError("Debit və credit bərabər olmalıdır.")
        seed_minimal_coa()
        entry = JournalEntry.objects.create(
            code=_next_je_code(),
            entry_date=entry_date,
            memo=memo or "",
            source=source or "",
            posted=bool(posted),
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
    @transaction.atomic
    def post_to_gl(cls, entry: JournalEntry, *, actor=None) -> JournalEntry:
        """Baş kitaba yaz — mühasib."""
        if entry.posted:
            return entry
        assert_period_open(entry.entry_date)
        entry.posted = True
        entry.save(update_fields=["posted"])
        return entry

    @classmethod
    def journal_from_invoice(cls, invoice, *, net=None, vat=None, posted: bool = False) -> JournalEntry:
        seed_minimal_coa()
        total = invoice.total or Decimal("0")
        net = Decimal(net if net is not None else total)
        vat = Decimal(vat if vat is not None else 0)
        lines = [
            {"account_code": code_for("ar"), "debit": total, "credit": 0, "memo": invoice.code},
            {"account_code": code_for("rent_revenue"), "debit": 0, "credit": net, "memo": invoice.code},
        ]
        if vat > 0:
            lines.append(
                {
                    "account_code": code_for("vat"),
                    "debit": 0,
                    "credit": vat,
                    "memo": f"VAT {invoice.code}",
                }
            )
        return cls.post_journal(
            memo=f"Invoice {invoice.code}",
            source="billing.invoice",
            entry_date=invoice.issue_date or timezone.localdate(),
            lines=lines,
            posted=posted,
        )

    @classmethod
    def journal_from_payment(cls, payment, *, posted: bool = False) -> JournalEntry:
        seed_minimal_coa()
        amount = payment.amount or Decimal("0")
        inv = payment.invoice
        method = (payment.method or "bank").lower()
        cash_code = code_for("cash") if method == "cash" else code_for("bank")
        return cls.post_journal(
            memo=f"Payment {inv.code if inv else payment.pk}",
            source="billing.payment",
            entry_date=payment.paid_at or timezone.localdate(),
            lines=[
                {"account_code": cash_code, "debit": amount, "credit": 0},
                {"account_code": code_for("ar"), "debit": 0, "credit": amount},
            ],
            posted=posted,
        )

    @classmethod
    @transaction.atomic
    def close_period(cls, *, year: int, month: int, actor=None) -> AccountingPeriod:
        period = ensure_period(year, month)
        if period.is_closed:
            return period
        period.is_closed = True
        period.closed_at = timezone.now()
        period.closed_by = actor
        period.save(update_fields=["is_closed", "closed_at", "closed_by"])
        return period

    @classmethod
    @transaction.atomic
    def reopen_period(cls, *, year: int, month: int) -> AccountingPeriod:
        period = ensure_period(year, month)
        period.is_closed = False
        period.closed_at = None
        period.closed_by = None
        period.save(update_fields=["is_closed", "closed_at", "closed_by"])
        return period
