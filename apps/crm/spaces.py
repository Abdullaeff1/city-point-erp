"""Satış üçün əlçatan sahələr — siyahı/detail köməkçiləri."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.crm.dashboard import available_spaces_qs
from apps.leases.models import Lease, LeaseStatus
from apps.property.models import ParkingAssignment, Space


def space_display_area(space: Space) -> Decimal | None:
    if space.rentable_area_m2 is not None:
        return Decimal(str(space.rentable_area_m2))
    if space.area_m2 is not None:
        return Decimal(str(space.area_m2))
    return None


def is_space_available_now(space: Space, *, today=None) -> bool:
    today = today or timezone.localdate()
    available, _conflicts = available_spaces_qs(today=today)
    return available.filter(pk=space.pk).exists()


def available_space_rows(*, limit: int | None = None) -> list[dict]:
    available, _ = available_spaces_qs()
    qs = available.order_by("floor__code", "code")
    if limit is not None:
        qs = qs[:limit]
    rows = []
    for s in qs:
        rows.append(
            {
                "space": s,
                "code": s.code,
                "label": s.area_code,
                "floor": s.floor.code if s.floor_id else "",
                "area_m2": space_display_area(s),
                "availability_date": s.availability_date,
                "base_rent_rate": s.base_rent_rate,
                "fit_out_status": s.fit_out_status,
                "renovation_needed": s.renovation_needed,
                "has_internal_kitchen": s.has_internal_kitchen,
                "parking_included": s.parking_included,
                "parking_slots": s.parking_slots,
                "url": reverse("erp:crm_space_detail", kwargs={"code": s.code}),
            }
        )
    return rows


def lease_history_for_space(space: Space) -> list[dict]:
    """Prior + current leases touching this space (space FK or lease lines)."""
    leases = (
        Lease.objects.filter(Q(space=space) | Q(lines__space=space))
        .select_related("party")
        .distinct()
        .order_by("-start_date", "-created_at")
    )
    rows = []
    for lease in leases:
        party_name = ""
        if lease.party_id:
            party_name = lease.party.display_name
        rows.append(
            {
                "code": lease.code,
                "party_name": party_name or "—",
                "status": lease.get_status_display(),
                "status_code": lease.status,
                "start_date": lease.start_date,
                "end_date": lease.end_date,
                "is_current": lease.status
                in (LeaseStatus.ACTIVE, LeaseStatus.EXPIRING, LeaseStatus.SIGNED),
                "url": reverse("erp:lease_detail", kwargs={"code": lease.code}),
            }
        )
    return rows


def parking_assignments_for_space(space: Space) -> list[ParkingAssignment]:
    return list(
        ParkingAssignment.objects.filter(space=space)
        .select_related("spot", "spot__zone", "party", "lease", "employee")
        .order_by("spot__zone__code", "spot__code")
    )


def build_crm_space_detail(space: Space) -> dict:
    today = timezone.localdate()
    available_now = is_space_available_now(space, today=today)
    return {
        "space": space,
        "area_m2": space_display_area(space),
        "available_now": available_now,
        "lease_history": lease_history_for_space(space),
        "parking_assignments": parking_assignments_for_space(space),
        "list_url": reverse("erp:crm_available_spaces"),
    }
