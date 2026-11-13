"""CRM pipeline helpers — manual steps, no silent auto-create."""

from __future__ import annotations

from django.db import transaction

from apps.core.services import Service
from apps.crm.models import Lead, LeadStatus, Offer, Opportunity, Qualification
from apps.crm.services import (
    CrmLeadService,
    CrmOfferService,
    CrmOpportunityService,
    convert_offer_to_lease_draft,
)


class CrmService(Service):
    @classmethod
    def qualify_lead(cls, lead: Lead, *, actor=None) -> Lead:
        if actor is not None:
            return CrmLeadService.update_lead(
                lead,
                actor=actor,
                data={"qualification": Qualification.POTENTIAL, "status": LeadStatus.QUALIFIED},
            )
        lead.qualification = Qualification.POTENTIAL
        lead.status = LeadStatus.QUALIFIED
        lead.save(update_fields=["qualification", "status", "updated_at"])
        return lead

    @classmethod
    @transaction.atomic
    def create_opportunity_from_lead(cls, lead: Lead, *, title: str = "", actor=None) -> Opportunity:
        if actor is not None:
            return CrmOpportunityService.create_from_lead(lead, actor=actor, title=title)
        from apps.crm.models import OpportunityStatus, PipelineStage

        opp = Opportunity.objects.create(
            lead=lead,
            title=(title or f"{lead.full_name or lead.company_name or 'Lead'} — İmkan")[:200],
            status=OpportunityStatus.OPEN,
            pipeline_stage=PipelineStage.WORKING,
            party=lead.party,
            expected_area=lead.max_area_m2 or lead.min_area_m2,
            employee_count=lead.employee_count,
            space=lead.interested_space,
            notes=lead.message or "",
        )
        lead.status = LeadStatus.QUALIFIED
        lead.qualification = Qualification.POTENTIAL
        lead.save(update_fields=["status", "qualification", "updated_at"])
        return opp

    @classmethod
    @transaction.atomic
    def create_offer(cls, *, opportunity, party, space=None, proposed_rent=0, notes="", actor=None):
        if actor is not None:
            return CrmOfferService.create_offer(
                actor=actor,
                opportunity=opportunity,
                party=party,
                space=space,
                notes=notes,
            )
        return Offer.objects.create(
            opportunity=opportunity,
            party=party,
            space=space,
            rent_amount=proposed_rent or 0,
            notes=notes or "",
        )

    @classmethod
    def accept_offer_to_lease(cls, offer: Offer):
        return convert_offer_to_lease_draft(offer)
