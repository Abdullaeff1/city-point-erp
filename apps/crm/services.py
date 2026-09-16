from django.db import transaction

from apps.crm.models import Offer, OfferStatus, OpportunityStatus
from apps.leases.models import Lease, LeaseStatus
from apps.leases.services import next_lease_code


@transaction.atomic
def convert_offer_to_lease_draft(offer: Offer) -> Lease:
    """Create a draft Lease from an accepted/ready Offer and link it back."""
    if offer.lease_id:
        return offer.lease

    lease = Lease.objects.create(
        code=next_lease_code(),
        party=offer.party,
        space=offer.space,
        status=LeaseStatus.DRAFT,
        rent=offer.rent_amount or 0,
        notes=offer.notes or "",
    )
    offer.lease = lease
    offer.status = OfferStatus.ACCEPTED
    offer.save(update_fields=["lease", "status"])

    opportunity = offer.opportunity
    if opportunity and opportunity.status == OpportunityStatus.OPEN:
        opportunity.status = OpportunityStatus.WON
        opportunity.save(update_fields=["status"])

    return lease
