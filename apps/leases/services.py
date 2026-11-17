from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.leases.models import Lease, LeaseStatus


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


def sync_space_from_lease(lease: Lease):
    """Update Space.commercial_status from lease state (no FK from Space → Lease)."""
    from apps.property.models import CommercialStatus, Space

    if not lease.space_id:
        return

    space = Space.objects.filter(pk=lease.space_id).first()
    if not space:
        return

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
    if new_status and space.commercial_status != new_status:
        space.commercial_status = new_status
        space.save(update_fields=["commercial_status"])


@transaction.atomic
def activate_lease(lease: Lease, actor=None):
    """Active lease cascade: space commercial=active, party resident, portal/access/billing flags."""
    from apps.parties.models import PartyRole, PartyRoleCode, PartyStatus
    from apps.property.models import CommercialStatus, Occupancy

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

    if lease.space_id:
        # Reload from DB — avoid overwriting sync_space_from_lease with stale related cache.
        space = type(lease.space).objects.get(pk=lease.space_id)
        space.occupancy = Occupancy.ACTIVE_LEASE
        space.commercial_status = CommercialStatus.ACTIVE
        if lease.party and lease.party.legacy_resident_company_id:
            space.resident_id = lease.party.legacy_resident_company_id
        space.save(update_fields=["occupancy", "resident", "commercial_status"])

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

    from apps.core import events as bus

    bus.emit(
        bus.LEASE_ACTIVATED,
        payload={"lease_id": lease.pk, "code": lease.code, "entity_model": "lease"},
        actor=actor,
    )
    return lease


@transaction.atomic
def terminate_lease(lease: Lease, actor=None):
    from apps.property.models import Occupancy

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
    if lease.space_id:
        space = type(lease.space).objects.get(pk=lease.space_id)
        space.occupancy = Occupancy.VACANT
        space.save(update_fields=["occupancy"])
    from apps.core import events as bus

    bus.emit(
        bus.LEASE_TERMINATED,
        payload={"lease_id": lease.pk, "code": lease.code, "entity_model": "lease"},
        actor=actor,
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
    if lease.space_id:
        from apps.property.models import CommercialStatus

        space = type(lease.space).objects.get(pk=lease.space_id)
        if space.commercial_status != CommercialStatus.NOTICE:
            space.commercial_status = CommercialStatus.NOTICE
            space.save(update_fields=["commercial_status"])
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
