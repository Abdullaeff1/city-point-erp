"""CRM pipeline strip counts for hunisi UI."""

from __future__ import annotations

from django.db.models import Q

from apps.crm.models import Lead, LeaseApplication, Offer, Opportunity, OfferStatus, Qualification


def pipeline_strip_counts() -> list[dict]:
    """Lid → İmkan → Təklif → Müqavilə stage counts for strip UI."""
    leads = Lead.objects.filter(
        ~Q(qualification=Qualification.NON_POTENTIAL),
        record_status__in=("open", "waiting"),
    ).count()
    opps = Opportunity.objects.filter(status="open").count()
    offers = Offer.objects.filter(
        status__in=(
            OfferStatus.DRAFT,
            OfferStatus.PENDING_APPROVAL,
            OfferStatus.APPROVED,
            OfferStatus.SENT,
            OfferStatus.NEGOTIATION,
        )
    ).count()
    apps = LeaseApplication.objects.exclude(status__in=("completed", "cancelled")).count()
    return [
        {"key": "leads", "label": "Lid", "count": leads, "url_name": "erp:crm_leads"},
        {"key": "opportunities", "label": "İmkan", "count": opps, "url_name": "erp:crm_opportunities"},
        {"key": "offers", "label": "Təklif", "count": offers, "url_name": "erp:crm_offers"},
        {
            "key": "applications",
            "label": "Müqavilə",
            "count": apps,
            "url_name": "erp:crm_lease_applications",
        },
    ]
