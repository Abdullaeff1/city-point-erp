"""CRM pipeline helpers (Phase 4) — manual steps, no silent auto-create."""

from __future__ import annotations

from django.db import transaction

from apps.core.services import Service
from apps.crm.models import Lead, LeadStatus, Offer, OfferStatus, Opportunity, OpportunityStatus
from apps.crm.services import convert_offer_to_lease_draft


class CrmService(Service):
    @classmethod
    def qualify_lead(cls, lead: Lead) -> Lead:
        lead.status = LeadStatus.QUALIFIED
        lead.save(update_fields=["status"])
        return lead

    @classmethod
    @transaction.atomic
    def create_opportunity_from_lead(cls, lead: Lead, *, title: str = "") -> Opportunity:
        opp = Opportunity.objects.create(
            lead=lead,
            title=(title or f"{lead.full_name} — {lead.company_name or 'Lead'}")[:200],
            status=OpportunityStatus.OPEN,
            party=lead.party,
            notes=lead.message or "",
        )
        lead.status = LeadStatus.QUALIFIED
        lead.save(update_fields=["status"])
        return opp

    @classmethod
    @transaction.atomic
    def create_offer(
        cls,
        *,
        opportunity: Opportunity,
        party,
        space=None,
        proposed_rent=0,
        notes="",
    ) -> Offer:
        return Offer.objects.create(
            opportunity=opportunity,
            party=party,
            space=space,
            status=OfferStatus.DRAFT,
            rent_amount=proposed_rent or 0,
            notes=notes or "",
        )

    @classmethod
    def accept_offer_to_lease(cls, offer: Offer):
        return convert_offer_to_lease_draft(offer)
