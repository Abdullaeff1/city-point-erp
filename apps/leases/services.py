from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.leases.models import Lease, LeaseLine, LeaseStatus

# Occupancy / portal still treat these as "open" commercial leases.
OPEN_LEASE_STATUSES = (
    LeaseStatus.ACTIVE,
    LeaseStatus.EXPIRING,
    LeaseStatus.RENEWED,
    LeaseStatus.AMENDED,
)

# Pre-active + active commercial holds (offer bind / reservation through occupancy).
COMMERCIAL_HOLD_STATUSES = (
    LeaseStatus.NEGOTIATION,
    LeaseStatus.APPROVED,
    LeaseStatus.SIGNED,
    *OPEN_LEASE_STATUSES,
)


def next_lease_code():
    """Allocate next LS-* code under row lock (call inside transaction.atomic)."""
    latest = (
        Lease.objects.select_for_update()
        .filter(code__startswith="LS-")
        .order_by("-pk")
        .values_list("code", flat=True)
        .first()
    )
    nxt = 1001
    if latest:
        try:
            nxt = int(str(latest).split("-", 1)[1]) + 1
        except (IndexError, ValueError):
            codes = Lease.objects.filter(code__startswith="LS-").values_list("code", flat=True)
            numbers = []
            for code in codes:
                try:
                    numbers.append(int(str(code).split("-", 1)[1]))
                except (IndexError, ValueError):
                    continue
            nxt = (max(numbers) + 1) if numbers else 1001
    return f"LS-{nxt}"


def lease_space_ids(lease: Lease) -> list[int]:
    """Primary space + LeaseLine spaces (deduped, primary first)."""
    ids: list[int] = []
    if lease.space_id:
        ids.append(int(lease.space_id))
    line_ids = (
        LeaseLine.objects.filter(lease_id=lease.pk)
        .exclude(space_id=None)
        .values_list("space_id", flat=True)
    )
    for sid in line_ids:
        sid = int(sid)
        if sid not in ids:
            ids.append(sid)
    return ids


def ensure_primary_lease_line(lease: Lease) -> LeaseLine | None:
    """Ensure a LeaseLine exists for ``lease.space`` (area from space when available)."""
    if not lease.space_id:
        return None
    space = lease.space
    area = None
    if space is not None:
        area = space.rentable_area_m2 or space.area_m2
    line, _created = LeaseLine.objects.get_or_create(
        lease=lease,
        space_id=lease.space_id,
        defaults={"area_m2": area},
    )
    return line


def space_held_by_other_open_lease(space_id: int, *, exclude_lease_id: int | None = None) -> bool:
    """True if another open lease still claims this space (primary or line)."""
    qs = Lease.objects.filter(status__in=OPEN_LEASE_STATUSES).filter(
        Q(space_id=space_id) | Q(lines__space_id=space_id)
    )
    if exclude_lease_id:
        qs = qs.exclude(pk=exclude_lease_id)
    return qs.distinct().exists()


def space_commercially_held(
    space_id: int, *, exclude_lease_id: int | None = None
) -> bool:
    """True if another lease commercially holds the space (reserved/contracted/active)."""
    qs = Lease.objects.filter(status__in=COMMERCIAL_HOLD_STATUSES).filter(
        Q(space_id=space_id) | Q(lines__space_id=space_id)
    )
    if exclude_lease_id:
        qs = qs.exclude(pk=exclude_lease_id)
    return qs.distinct().exists()


def lock_space_for_reservation(space_id: int):
    """Row-lock Space for concurrent commercial reservation (call inside atomic)."""
    from apps.property.models import Space

    return Space.objects.select_for_update().get(pk=space_id)


def party_has_other_open_leases(party_id: int, *, exclude_lease_id: int | None = None) -> bool:
    qs = Lease.objects.filter(party_id=party_id, status__in=OPEN_LEASE_STATUSES)
    if exclude_lease_id:
        qs = qs.exclude(pk=exclude_lease_id)
    return qs.exists()


def sync_space_from_lease(lease: Lease):
    """Update commercial_status on primary + all LeaseLine spaces."""
    from apps.property.models import CommercialStatus, Space

    mapping = {
        LeaseStatus.DRAFT: CommercialStatus.VACANT,
        LeaseStatus.NEGOTIATION: CommercialStatus.RESERVED,
        LeaseStatus.APPROVED: CommercialStatus.CONTRACTED,
        LeaseStatus.SIGNED: CommercialStatus.CONTRACTED,
        LeaseStatus.ACTIVE: CommercialStatus.ACTIVE,
        LeaseStatus.EXPIRING: CommercialStatus.NOTICE,
        LeaseStatus.RENEWED: CommercialStatus.ACTIVE,
        LeaseStatus.AMENDED: CommercialStatus.ACTIVE,
        LeaseStatus.TERMINATED: CommercialStatus.VACANT,
    }
    new_status = mapping.get(lease.status)
    if not new_status:
        return
    ids = lease_space_ids(lease)
    if not ids:
        return
    for space in Space.objects.filter(pk__in=ids):
        # Don't force VACANT if another commercial hold still claims the space.
        if (
            new_status == CommercialStatus.VACANT
            and space_commercially_held(space.pk, exclude_lease_id=lease.pk)
        ):
            continue
        if space.commercial_status != new_status:
            space.commercial_status = new_status
            space.save(update_fields=["commercial_status"])


def apply_space_bridge_from_lease(lease: Lease, *, occupying: bool) -> None:
    """Set/clear occupancy + Space.resident bridge for all lease spaces."""
    from apps.property.models import Occupancy, Space

    ids = lease_space_ids(lease)
    if not ids:
        return
    company_id = None
    if occupying and lease.party_id:
        company_id = getattr(lease.party, "legacy_resident_company_id", None)

    for space in Space.objects.filter(pk__in=ids):
        if occupying:
            space.occupancy = Occupancy.ACTIVE_LEASE
            if company_id:
                space.resident_id = company_id
            space.save(update_fields=["occupancy", "resident"])
            continue
        if space_held_by_other_open_lease(space.pk, exclude_lease_id=lease.pk):
            continue
        space.occupancy = Occupancy.VACANT
        space.resident_id = None
        space.save(update_fields=["occupancy", "resident"])


@transaction.atomic
def activate_lease(lease: Lease, actor=None):
    """Active lease cascade: all spaces, party resident, portal/access/billing flags.

    Idempotent under concurrent calls: row-locks the lease; already-ACTIVE leases
    only re-ensure the deposit charge (no duplicate cascade/events).
    """
    from apps.leases.lease_ops import ensure_deposit_charge
    from apps.parties.models import PartyRole, PartyRoleCode, PartyStatus
    from apps.property.models import CommercialStatus, Space

    lease = Lease.objects.select_for_update().get(pk=lease.pk)
    if lease.status == LeaseStatus.ACTIVE:
        ensure_deposit_charge(lease, actor=actor)
        return lease

    ensure_primary_lease_line(lease)

    lease.status = LeaseStatus.ACTIVE
    lease.billing_active = True
    lease.portal_eligible = True
    lease.access_eligible = True
    lease.activated_at = timezone.now()
    lease.terminated_at = None
    lease.save(
        update_fields=[
            "status",
            "billing_active",
            "portal_eligible",
            "access_eligible",
            "activated_at",
            "terminated_at",
            "updated_at",
        ]
    )
    sync_space_from_lease(lease)
    apply_space_bridge_from_lease(lease, occupying=True)
    # Keep commercial ACTIVE on all spaces (sync already did; reinforce after bridge).
    Space.objects.filter(pk__in=lease_space_ids(lease)).exclude(
        commercial_status=CommercialStatus.ACTIVE
    ).update(commercial_status=CommercialStatus.ACTIVE)

    party = lease.party
    if party:
        if party.status != PartyStatus.ACTIVE:
            party.status = PartyStatus.ACTIVE
            party.save(update_fields=["status", "updated_at"])
        PartyRole.objects.get_or_create(
            party=party,
            role=PartyRoleCode.RESIDENT,
            defaults={"is_primary": True},
        )
        if party.legacy_resident_company_id:
            company = party.legacy_resident_company
            company.portal_active = True
            company.status = "active"
            company.save(update_fields=["portal_active", "status"])

    ensure_deposit_charge(lease, actor=actor)

    from apps.core import events as bus

    bus.emit(
        bus.LEASE_ACTIVATED,
        payload={"lease_id": lease.pk, "code": lease.code, "entity_model": "lease"},
        actor=actor,
        event_key=f"lease.activated.{lease.pk}",
    )
    return lease


@transaction.atomic
def terminate_lease(lease: Lease, actor=None):
    lease.status = LeaseStatus.TERMINATED
    lease.billing_active = False
    lease.portal_eligible = False
    lease.access_eligible = False
    lease.terminated_at = timezone.now()
    lease.save(
        update_fields=[
            "status",
            "billing_active",
            "portal_eligible",
            "access_eligible",
            "terminated_at",
            "updated_at",
        ]
    )
    sync_space_from_lease(lease)
    apply_space_bridge_from_lease(lease, occupying=False)

    party = lease.party
    if party and party.legacy_resident_company_id:
        if not party_has_other_open_leases(party.pk, exclude_lease_id=lease.pk):
            company = party.legacy_resident_company
            if company.portal_active:
                company.portal_active = False
                company.save(update_fields=["portal_active"])

    from apps.core import events as bus

    bus.emit(
        bus.LEASE_TERMINATED,
        payload={"lease_id": lease.pk, "code": lease.code, "entity_model": "lease"},
        actor=actor,
        event_key=f"lease.terminated.{lease.pk}",
    )
    return lease


def _notify_lease_expiring(lease: Lease) -> None:
    """Idempotent in-app notice for CRM/sales staff (event_key dedup)."""
    from django.contrib.auth import get_user_model

    from apps.accounts.models import Role
    from apps.comms.services import notify_in_app

    User = get_user_model()
    msg = (
        f"Müqavilə {lease.code} bitməyə yaxındır "
        f"(bitmə: {lease.end_date}). Uzatma/xitam yoxlanmalıdır."
    )
    event_key = f"lease.expiring.{lease.pk}.{lease.end_date}"
    for user in User.objects.filter(
        is_active=True,
        role__in={Role.ADMIN, Role.MANAGEMENT, Role.SALES},
    ).iterator(chunk_size=50):
        notify_in_app(user=user, message=msg, event_key=event_key)


@transaction.atomic
def mark_lease_expiring(lease: Lease, *, actor=None) -> Lease:
    if lease.status != LeaseStatus.ACTIVE:
        return lease
    lease.status = LeaseStatus.EXPIRING
    lease.save(update_fields=["status", "updated_at"])
    sync_space_from_lease(lease)
    from apps.core import events as bus

    bus.emit(
        bus.LEASE_EXPIRING,
        payload={
            "lease_id": lease.pk,
            "code": lease.code,
            "status": LeaseStatus.EXPIRING,
            "end_date": str(lease.end_date) if lease.end_date else "",
            "entity_model": "lease",
        },
        actor=actor,
        event_key=f"lease.expiring.{lease.pk}.{lease.end_date}",
    )
    _notify_lease_expiring(lease)
    return lease


def process_lease_lifecycle(*, as_of=None, expiring_days: int | None = None) -> dict:
    """
    Scheduled lifecycle:
    - SIGNED + start_date <= as_of → activate (space/portal/billing cascade)
    - ACTIVE + end_date within notice window → EXPIRING + notify
    """
    as_of = as_of or timezone.localdate()
    if expiring_days is None:
        expiring_days = int(getattr(settings, "LEASE_EXPIRING_NOTICE_DAYS", 90))
    notice_until = as_of + timedelta(days=max(expiring_days, 0))

    activated = 0
    marked_expiring = 0
    to_activate = list(
        Lease.objects.filter(
            status=LeaseStatus.SIGNED,
            start_date__isnull=False,
            start_date__lte=as_of,
        ).values_list("pk", flat=True)
    )
    for pk in to_activate:
        with transaction.atomic():
            lease = Lease.objects.select_for_update().filter(pk=pk).first()
            if lease and lease.status == LeaseStatus.SIGNED:
                activate_lease(lease)
                activated += 1

    to_expire = list(
        Lease.objects.filter(
            status=LeaseStatus.ACTIVE,
            end_date__isnull=False,
            end_date__lte=notice_until,
        ).values_list("pk", flat=True)
    )
    for pk in to_expire:
        with transaction.atomic():
            lease = Lease.objects.select_for_update().filter(pk=pk).first()
            if lease and lease.status == LeaseStatus.ACTIVE:
                mark_lease_expiring(lease)
                marked_expiring += 1

    return {
        "as_of": str(as_of),
        "expiring_days": expiring_days,
        "activated": activated,
        "marked_expiring": marked_expiring,
    }
