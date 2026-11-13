"""Lease draft + recurring charge foundation (A.4 / Phase 3 / 11)."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Charge, ChargeSource
from apps.core.services import Service
from apps.leases.models import DepositSettlement, Lease, LeaseStatus
from apps.leases.services import next_lease_code

TWOPLACES = Decimal("0.01")


def _q(amount) -> Decimal:
    return Decimal(str(amount or 0)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def lease_area_m2(lease: Lease) -> Decimal:
    """Rentable m²: LeaseLine sum → space.rentable_area_m2 → space.area_m2."""
    lines = list(lease.lines.all()) if lease.pk else []
    if lines:
        total = sum((Decimal(str(ln.area_m2 or 0)) for ln in lines), Decimal("0"))
        if total > 0:
            return total
    space = lease.space
    if space is not None:
        if space.rentable_area_m2 and space.rentable_area_m2 > 0:
            return Decimal(str(space.rentable_area_m2))
        if space.area_m2 and space.area_m2 > 0:
            return Decimal(str(space.area_m2))
    return Decimal("0")


def prorata_factor(*, period_start: date, period_end: date, lease_start: date | None) -> Decimal:
    """Fraction of period the lease is active (mid-month start)."""
    days_in_period = (period_end - period_start).days + 1
    if days_in_period <= 0:
        return Decimal("0")
    if not lease_start or lease_start <= period_start:
        return Decimal("1")
    if lease_start > period_end:
        return Decimal("0")
    active_days = (period_end - lease_start).days + 1
    return (Decimal(active_days) / Decimal(days_in_period)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def compute_lease_amounts(lease: Lease, *, factor: Decimal | None = None) -> dict:
    """Monthly net amounts from m² × rate (A.4). factor=1 full month."""
    area = lease_area_m2(lease)
    f = factor if factor is not None else Decimal("1")
    rent_rate = Decimal(str(lease.rent_rate_per_m2 or 0))
    sc_rate = Decimal(str(lease.service_rate_per_m2 or 0))
    if rent_rate > 0 and area > 0:
        rent = _q(area * rent_rate * f)
    else:
        rent = _q(Decimal(str(lease.rent or 0)) * f)
    if sc_rate > 0 and area > 0:
        service = _q(area * sc_rate * f)
    else:
        service = _q(Decimal(str(lease.service_charge or 0)) * f)
    addons = []
    if lease.pk:
        for addon in lease.addons.filter(is_active=True):
            rate = Decimal(str(addon.rate_per_m2 or 0))
            if rate <= 0 or area <= 0:
                continue
            amt = _q(area * rate * f)
            addons.append({"addon": addon, "amount": amt, "label": addon.label})
    deposit_months = int(lease.deposit_months or 2)
    full_month_rent = rent if f == 1 else (
        _q(area * rent_rate) if rent_rate > 0 and area > 0 else _q(lease.rent)
    )
    deposit = (
        _q(lease.deposit)
        if lease.deposit and Decimal(str(lease.deposit)) > 0
        else _q(full_month_rent * deposit_months)
    )
    return {
        "area_m2": area,
        "rent": rent,
        "service_charge": service,
        "addons": addons,
        "deposit": deposit,
        "factor": f,
    }


def refresh_lease_cached_amounts(lease: Lease) -> Lease:
    """Update rent/service_charge/deposit cache from rates."""
    amounts = compute_lease_amounts(lease, factor=Decimal("1"))
    lease.rent = amounts["rent"]
    lease.service_charge = amounts["service_charge"]
    if not lease.deposit or Decimal(str(lease.deposit)) <= 0:
        lease.deposit = amounts["deposit"]
    lease.save(update_fields=["rent", "service_charge", "deposit", "updated_at"])
    return lease


def month_bounds(as_of: date) -> tuple[date, date]:
    period_start = as_of.replace(day=1)
    last = monthrange(as_of.year, as_of.month)[1]
    period_end = as_of.replace(day=last)
    return period_start, period_end


class LeaseService(Service):
    @classmethod
    @transaction.atomic
    def create_draft(
        cls,
        *,
        party,
        space=None,
        start_date=None,
        end_date=None,
        rent=0,
        service_charge=0,
        deposit=0,
        rent_rate_per_m2=0,
        service_rate_per_m2=0,
        deposit_months=2,
        parking_notes="",
        notes="",
    ) -> Lease:
        cls.require(party is not None, "Party tələb olunur.")
        rent_rate = Decimal(str(rent_rate_per_m2 or 0))
        sc_rate = Decimal(str(service_rate_per_m2 or 0))
        if space is not None:
            if rent_rate <= 0 and space.base_rent_rate:
                rent_rate = Decimal(str(space.base_rent_rate))
            if sc_rate <= 0 and space.service_charge_rate:
                sc_rate = Decimal(str(space.service_charge_rate))
        lease = Lease.objects.create(
            code=next_lease_code(),
            party=party,
            space=space,
            status=LeaseStatus.DRAFT,
            start_date=start_date,
            end_date=end_date,
            rent=Decimal(str(rent or 0)),
            service_charge=Decimal(str(service_charge or 0)),
            deposit=Decimal(str(deposit or 0)),
            rent_rate_per_m2=rent_rate,
            service_rate_per_m2=sc_rate,
            deposit_months=int(deposit_months or 2),
            parking_included_free=True,
            parking_notes=parking_notes or "",
            notes=notes or "",
        )
        refresh_lease_cached_amounts(lease)
        return lease

    @classmethod
    def advance_status(cls, lease: Lease, new_status: str) -> Lease:
        allowed = {c.value for c in LeaseStatus}
        cls.require(new_status in allowed, "Naməlum lease status.")
        lease.status = new_status
        lease.save(update_fields=["status", "updated_at"])
        return lease

    @classmethod
    @transaction.atomic
    def settle_deposit(
        cls,
        lease: Lease,
        *,
        kind: str = DepositSettlement.Kind.FULL_RETURN,
        withhold_amount=0,
        reason: str = "",
        settled_at=None,
    ) -> DepositSettlement:
        deposit = Decimal(str(lease.deposit or 0))
        withhold = _q(withhold_amount)
        if kind == DepositSettlement.Kind.FULL_RETURN:
            amount = deposit
            withhold = Decimal("0")
        elif kind == DepositSettlement.Kind.WITHHOLD:
            amount = Decimal("0")
            withhold = deposit if withhold <= 0 else withhold
        else:
            amount = _q(deposit - withhold)
        return DepositSettlement.objects.create(
            lease=lease,
            kind=kind,
            amount=amount,
            withhold_amount=withhold,
            reason=reason or "",
            settled_at=settled_at or timezone.localdate(),
        )


def generate_monthly_lease_charges(*, as_of: date | None = None) -> dict:
    """Create rent + SC + addon Charge rows (m² × rate, prorrata). No parking."""
    as_of = as_of or timezone.localdate()
    period_start, period_end = month_bounds(as_of)

    created = 0
    skipped = 0
    for lease in Lease.objects.filter(
        status=LeaseStatus.ACTIVE, billing_active=True
    ).select_related("party", "space").prefetch_related("lines", "addons"):
        factor = prorata_factor(
            period_start=period_start,
            period_end=period_end,
            lease_start=lease.start_date,
        )
        if factor <= 0:
            skipped += 1
            continue
        amounts = compute_lease_amounts(lease, factor=factor)
        rows = [
            (ChargeSource.RENT, amounts["rent"], "Kirayə"),
            (ChargeSource.SERVICE_CHARGE, amounts["service_charge"], "Xidmət haqqı"),
        ]
        for addon_row in amounts["addons"]:
            rows.append(
                (
                    ChargeSource.ADDITIONAL,
                    addon_row["amount"],
                    addon_row["label"],
                )
            )
        for source, amount, label in rows:
            if not amount or amount <= 0:
                continue
            # Addon uniqueness by description prefix
            qs = Charge.objects.filter(
                lease=lease,
                source=source,
                period_start=period_start,
                period_end=period_end,
            )
            if source == ChargeSource.ADDITIONAL:
                qs = qs.filter(description__startswith=f"{label} ")
            if qs.exists():
                skipped += 1
                continue
            desc = f"{label} {period_start:%Y-%m} · {lease.code}"
            if factor < 1:
                desc += f" · prorrata {factor}"
            Charge.objects.create(
                party=lease.party,
                lease=lease,
                space=lease.space,
                source=source,
                description=desc,
                amount=amount,
                currency=lease.currency or "AZN",
                period_start=period_start,
                period_end=period_end,
            )
            created += 1
    return {
        "created": created,
        "skipped": skipped,
        "period_start": str(period_start),
        "period_end": str(period_end),
    }
