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
    """Allocate next JE-* under row lock (call inside transaction.atomic)."""
    latest = (
        JournalEntry.objects.select_for_update()
        .filter(code__startswith="JE-")
        .order_by("-pk")
        .values_list("code", flat=True)
        .first()
    )
    nxt = 1001
    if latest:
        try:
            nxt = int(str(latest).split("-", 1)[1]) + 1
        except (IndexError, ValueError):
            codes = JournalEntry.objects.filter(code__startswith="JE-").values_list("code", flat=True)
            numbers = []
            for code in codes:
                try:
                    numbers.append(int(str(code).split("-", 1)[1]))
                except (IndexError, ValueError):
                    continue
            nxt = (max(numbers) + 1) if numbers else 1001
    return f"JE-{nxt}"


def _revenue_role_for_charge_source(source: str) -> str:
    from apps.billing.models import ChargeSource

    mapping = {
        ChargeSource.RENT: "rent_revenue",
        ChargeSource.SERVICE_CHARGE: "service_revenue",
        ChargeSource.PENALTY: "penalty_revenue",
        ChargeSource.PARKING: "other_revenue",
        ChargeSource.UTILITY: "other_revenue",
        ChargeSource.WORK_ORDER: "other_revenue",
        ChargeSource.ADDITIONAL: "other_revenue",
        ChargeSource.DEPOSIT: "other_revenue",
    }
    return mapping.get(source, "rent_revenue")


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
        source_ref: str = "",
        entry_date=None,
        actor=None,
        posted: bool = False,
    ) -> JournalEntry:
        """lines: [{account_code, debit, credit, memo?}] — debits must equal credits."""
        ref = (source_ref or "").strip()
        src = (source or "").strip()
        if ref and src:
            existing = JournalEntry.objects.filter(source=src, source_ref=ref).first()
            if existing:
                return existing
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
            source=src,
            source_ref=ref,
            posted=bool(posted),
        )
        for row in lines:
            try:
                acct = Account.objects.get(code=row["account_code"])
            except Account.DoesNotExist as exc:
                raise DomainError(f"Hesab tapılmadı: {row['account_code']}") from exc
            if not acct.is_active:
                raise DomainError(f"Hesab aktiv deyil: {acct.code}")
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
        from apps.audit.services import log_action

        log_action(
            action="accounting.journal.posted",
            actor=actor,
            entity=entry,
            new_values={"code": entry.code, "source_ref": entry.source_ref},
            source="finance",
        )
        return entry

    @classmethod
    @transaction.atomic
    def reverse_journal(cls, entry: JournalEntry, *, actor=None, memo: str = "") -> JournalEntry:
        """Create balancing reverse entry (same period rules). Idempotent per source_ref."""
        if entry.reversed_entry_id:
            return entry.reversed_entry
        ref = f"reverse:{entry.code}"
        existing = JournalEntry.objects.filter(source="accounting.reverse", source_ref=ref).first()
        if existing:
            if not entry.reversed_entry_id:
                entry.reversed_entry = existing
                entry.save(update_fields=["reversed_entry"])
            return existing
        assert_period_open(timezone.localdate())
        lines = []
        for ln in entry.lines.select_related("account"):
            lines.append(
                {
                    "account_code": ln.account.code,
                    "debit": ln.credit or 0,
                    "credit": ln.debit or 0,
                    "memo": f"REV {ln.memo or entry.code}",
                }
            )
        rev = cls.post_journal(
            lines=lines,
            memo=memo or f"Reversal of {entry.code}",
            source="accounting.reverse",
            source_ref=ref,
            entry_date=timezone.localdate(),
            actor=actor,
            posted=False,
        )
        entry.reversed_entry = rev
        entry.save(update_fields=["reversed_entry"])
        from apps.audit.services import log_action

        log_action(
            action="accounting.journal.reversed",
            actor=actor,
            entity=entry,
            new_values={"original": entry.code, "reversal": rev.code},
            source="finance",
        )
        return rev

    @classmethod
    def journal_from_invoice(cls, invoice, *, net=None, vat=None, posted: bool = False) -> JournalEntry:
        seed_minimal_coa()
        source_ref = f"invoice:{invoice.pk}"
        existing = JournalEntry.objects.filter(source="billing.invoice", source_ref=source_ref).first()
        if existing:
            return existing
        total = invoice.total or Decimal("0")
        vat = Decimal(vat if vat is not None else 0)
        # Prefer charge-linked lines for revenue split; fall back to single net credit.
        revenue_by_role: dict[str, Decimal] = {}
        charge_net = Decimal("0")
        for ln in invoice.lines.select_related("charge").all():
            if (ln.description or "").startswith("ƏDV"):
                continue
            amt = Decimal(ln.amount or 0)
            if amt == 0:
                continue
            role = "rent_revenue"
            if ln.charge_id and ln.charge:
                role = _revenue_role_for_charge_source(ln.charge.source)
            revenue_by_role[role] = revenue_by_role.get(role, Decimal("0")) + amt
            charge_net += amt
        if not revenue_by_role:
            net = Decimal(net if net is not None else (total - vat))
            revenue_by_role["rent_revenue"] = net
            charge_net = net
        elif net is not None and Decimal(net) != charge_net:
            # Keep explicit net override balanced on primary rent bucket if needed.
            diff = Decimal(net) - charge_net
            if diff != 0:
                revenue_by_role["rent_revenue"] = revenue_by_role.get("rent_revenue", Decimal("0")) + diff
        lines = [
            {"account_code": code_for("ar"), "debit": total, "credit": 0, "memo": invoice.code},
        ]
        for role, amt in revenue_by_role.items():
            if amt == 0:
                continue
            lines.append(
                {
                    "account_code": code_for(role),
                    "debit": 0,
                    "credit": amt,
                    "memo": invoice.code,
                }
            )
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
            source_ref=source_ref,
            entry_date=invoice.issue_date or timezone.localdate(),
            lines=lines,
            posted=posted,
        )

    @classmethod
    def journal_from_payment(cls, payment, *, posted: bool = False) -> JournalEntry:
        seed_minimal_coa()
        source_ref = f"payment:{payment.pk}"
        existing = JournalEntry.objects.filter(source="billing.payment", source_ref=source_ref).first()
        if existing:
            return existing
        amount = payment.amount or Decimal("0")
        inv = payment.invoice
        method = (payment.method or "bank").lower()
        cash_code = code_for("cash") if method == "cash" else code_for("bank")
        return cls.post_journal(
            memo=f"Payment {inv.code if inv else payment.pk}",
            source="billing.payment",
            source_ref=source_ref,
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
        from apps.audit.services import log_action

        log_action(
            action="accounting.period.closed",
            actor=actor,
            entity=period,
            new_values={"year": year, "month": month},
            source="finance",
        )
        return period

    @classmethod
    @transaction.atomic
    def reopen_period(cls, *, year: int, month: int, actor=None) -> AccountingPeriod:
        period = ensure_period(year, month)
        period.is_closed = False
        period.closed_at = None
        period.closed_by = None
        period.save(update_fields=["is_closed", "closed_at", "closed_by"])
        from apps.audit.services import log_action

        log_action(
            action="accounting.period.reopened",
            actor=actor,
            entity=period,
            new_values={"year": year, "month": month},
            source="finance",
        )
        return period
