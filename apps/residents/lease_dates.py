"""Lease / occupancy display helpers for resident company cards (Lease + Space SoT)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from apps.leases.models import Lease, LeaseStatus
from apps.parties.models import Party


@dataclass
class LeaseDateSummary:
    active_leases: list
    summary_start: date | None
    summary_end: date | None
    latest_lease: object | None
    show_latest_as_son: bool
    all_leases: list
    parking_assignments: list


def party_for_company(company):
    return Party.objects.filter(legacy_resident_company=company).first()


def leases_for_company(company):
    party_ids = Party.objects.filter(legacy_resident_company=company).values_list("id", flat=True)
    return (
        Lease.objects.filter(party_id__in=party_ids)
        .select_related("party", "space", "space__floor")
        .prefetch_related("lines__space__floor")
        .order_by("-start_date", "-id")
    )


def active_parking_qs():
    from django.db.models import Q
    from django.utils import timezone

    from apps.property.models import ParkingAssignment

    today = timezone.localdate()
    return (
        ParkingAssignment.objects.filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today),
            Q(start_date__isnull=True) | Q(start_date__lte=today),
            spot__is_active=True,
        )
        .select_related(
            "spot",
            "spot__zone",
            "space",
            "space__floor",
            "employee",
            "party",
            "party__legacy_resident_company",
        )
        .order_by(
            "party__legacy_resident_company__name",
            "spot__zone__code",
            "spot__code",
        )
    )


def parking_for_company(company):
    party_ids = Party.objects.filter(legacy_resident_company=company).values_list("id", flat=True)
    if not party_ids:
        return []
    return list(active_parking_qs().filter(party_id__in=party_ids))


def parking_for_company_ids(company_ids: list[int]):
    if not company_ids:
        return []
    return list(
        active_parking_qs().filter(party__legacy_resident_company_id__in=company_ids)
    )


def lease_date_summary(company) -> LeaseDateSummary:
    qs = list(leases_for_company(company))
    active = [L for L in qs if L.status == LeaseStatus.ACTIVE]
    parking = parking_for_company(company)
    if active:
        starts = [L.start_date for L in active if L.start_date]
        ends = [L.end_date for L in active if L.end_date]
        return LeaseDateSummary(
            active_leases=active,
            summary_start=min(starts) if starts else None,
            summary_end=max(ends) if ends else None,
            latest_lease=None,
            show_latest_as_son=False,
            all_leases=qs,
            parking_assignments=parking,
        )
    latest = qs[0] if qs else None
    return LeaseDateSummary(
        active_leases=[],
        summary_start=None,
        summary_end=None,
        latest_lease=latest,
        show_latest_as_son=latest is not None,
        all_leases=qs,
        parking_assignments=parking,
    )


def lease_display_rows(company) -> list[dict]:
    """Flat rows for İcarə və sahələr card (read-only)."""
    rows = []
    for lease in leases_for_company(company):
        space = lease.space
        area = None
        if space and space.area_m2 is not None:
            area = space.area_m2
        lines = list(lease.lines.all()) if hasattr(lease, "lines") else []
        if area is None and lines:
            areas = [ln.area_m2 for ln in lines if ln.area_m2 is not None]
            if areas:
                area = sum(areas)
        floor = getattr(space, "floor", None) if space else None
        rows.append(
            {
                "lease": lease,
                "code": lease.code,
                "start": lease.start_date,
                "end": lease.end_date,
                "status": lease.get_status_display(),
                "status_code": lease.status,
                "space": space,
                "space_label": space.short_label if space and hasattr(space, "short_label") else (
                    space.code if space else "—"
                ),
                "floor": str(floor) if floor else "—",
                "area_m2": area,
                "lease_type": lease.lease_type or "—",
                "rent": lease.rent,
                "currency": lease.currency,
                "deposit": lease.deposit,
                "is_active": lease.status == LeaseStatus.ACTIVE,
            }
        )
    return rows
