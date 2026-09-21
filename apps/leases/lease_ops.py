"""Lease draft + recurring charge foundation (Phase 3 / 11 bridge)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Charge, ChargeSource
from apps.core.services import Service
from apps.leases.models import Lease, LeaseStatus
from apps.leases.services import next_lease_code


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
        notes="",
    ) -> Lease:
        cls.require(party is not None, "Party tələb olunur.")
        return Lease.objects.create(
            code=next_lease_code(),
            party=party,
            space=space,
            status=LeaseStatus.DRAFT,
            start_date=start_date,
            end_date=end_date,
            rent=Decimal(str(rent or 0)),
            service_charge=Decimal(str(service_charge or 0)),
            deposit=Decimal(str(deposit or 0)),
            notes=notes or "",
        )

    @classmethod
    def advance_status(cls, lease: Lease, new_status: str) -> Lease:
        allowed = {c.value for c in LeaseStatus}
        cls.require(new_status in allowed, "Naməlum lease status.")
        lease.status = new_status
        lease.save(update_fields=["status", "updated_at"])
        return lease


def generate_monthly_lease_charges(*, as_of: date | None = None) -> dict:
    """Create rent + service_charge Charge rows for active leases (idempotent per period)."""
    as_of = as_of or timezone.localdate()
    period_start = as_of.replace(day=1)
    if period_start.month == 12:
        period_end = period_start.replace(year=period_start.year + 1, month=1, day=1)
    else:
        period_end = period_start.replace(month=period_start.month + 1, day=1)
    from datetime import timedelta

    period_end = period_end - timedelta(days=1)

    created = 0
    skipped = 0
    for lease in Lease.objects.filter(status=LeaseStatus.ACTIVE, billing_active=True).select_related("party", "space"):
        for source, amount, label in (
            (ChargeSource.RENT, lease.rent, "Kirayə"),
            (ChargeSource.SERVICE_CHARGE, lease.service_charge, "Xidmət haqqı"),
        ):
            if not amount or amount <= 0:
                continue
            exists = Charge.objects.filter(
                lease=lease,
                source=source,
                period_start=period_start,
                period_end=period_end,
            ).exists()
            if exists:
                skipped += 1
                continue
            Charge.objects.create(
                party=lease.party,
                lease=lease,
                space=lease.space,
                source=source,
                description=f"{label} {period_start:%Y-%m} · {lease.code}",
                amount=amount,
                currency=lease.currency or "AZN",
                period_start=period_start,
                period_end=period_end,
            )
            created += 1
    return {"created": created, "skipped": skipped, "period_start": str(period_start)}
