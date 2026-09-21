from django.db import transaction
from django.utils import timezone

from apps.leases.models import Lease, LeaseStatus


def next_lease_code():
    codes = Lease.objects.filter(code__startswith="LS-").values_list("code", flat=True)
    numbers = []
    for code in codes:
        try:
            numbers.append(int(code.split("-")[1]))
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

    try:
        from apps.audit.services import log_action

        log_action(action="lease.activated", actor=actor, entity=lease, source="leases")
    except Exception:
        pass
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
