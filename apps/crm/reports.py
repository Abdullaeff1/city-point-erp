"""CRM report metrics + XLSX export helpers."""

from __future__ import annotations

from io import BytesIO

from django.db.models import Count, Q
from django.utils import timezone

from apps.crm.models import (
    ActivityType,
    Lead,
    LeadActivity,
    LeaseApplication,
    LeaseApplicationStatus,
    Offer,
    OfferStatus,
    Opportunity,
    OpportunityStatus,
)


def filtered_leads(params: dict):
    qs = Lead.objects.all()
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if params.get("source"):
        qs = qs.filter(source=params["source"])
    if params.get("qualification"):
        qs = qs.filter(qualification=params["qualification"])
    if params.get("pipeline_stage"):
        qs = qs.filter(pipeline_stage=params["pipeline_stage"])
    if params.get("record_status"):
        qs = qs.filter(record_status=params["record_status"])
    if params.get("outcome"):
        qs = qs.filter(outcome=params["outcome"])
    if params.get("owner"):
        qs = qs.filter(owner_id=params["owner"])
    return qs


def build_crm_report(params: dict | None = None) -> dict:
    params = params or {}
    leads = filtered_leads(params)
    lead_ids = list(leads.values_list("pk", flat=True))
    opps = Opportunity.objects.filter(Q(lead_id__in=lead_ids) | Q(lead__isnull=True))
    if params.get("date_from"):
        opps = opps.filter(created_at__date__gte=params["date_from"])
    if params.get("date_to"):
        opps = opps.filter(created_at__date__lte=params["date_to"])
    offers = Offer.objects.filter(opportunity__in=opps)
    apps = LeaseApplication.objects.filter(opportunity__in=opps)

    viewings = LeadActivity.objects.filter(
        lead_id__in=lead_ids, activity_type=ActivityType.VIEWING
    ).count()
    meetings = LeadActivity.objects.filter(
        lead_id__in=lead_ids, activity_type=ActivityType.MEETING
    ).count()

    lead_count = leads.count()
    opp_count = opps.count()
    offer_sent = offers.filter(status=OfferStatus.SENT).count() + offers.filter(
        status=OfferStatus.ACCEPTED
    ).count()
    won = opps.filter(status=OpportunityStatus.WON).count()
    lost = opps.filter(status=OpportunityStatus.LOST).count()
    signed = apps.filter(
        status__in=(
            LeaseApplicationStatus.SIGNED_DOCUMENTS_RECEIVED,
            LeaseApplicationStatus.COMPLETED,
        )
    ).count()

    def _pct(num, den):
        return round((num / den) * 100, 1) if den else 0.0

    outcome_breakdown = list(
        leads.exclude(outcome="")
        .values("outcome")
        .annotate(c=Count("id"))
        .order_by("-c")
    )
    stage_breakdown = list(
        leads.values("pipeline_stage").annotate(c=Count("id")).order_by("-c")
    )

    return {
        "lead_count": lead_count,
        "viewings": viewings,
        "meetings": meetings,
        "opportunity_count": opp_count,
        "offer_sent": offer_sent,
        "won": won,
        "lost": lost,
        "signed_leases": signed,
        "conversion_lead_to_opp": _pct(opp_count, lead_count),
        "conversion_opp_to_offer": _pct(offer_sent, opp_count),
        "conversion_offer_to_signed": _pct(signed, offer_sent or offers.count()),
        "outcome_breakdown": outcome_breakdown,
        "stage_breakdown": stage_breakdown,
        "generated_at": timezone.now(),
    }


def export_crm_xlsx(params: dict | None = None) -> bytes:
    from openpyxl import Workbook

    params = params or {}
    report = build_crm_report(params)
    leads = filtered_leads(params).select_related("owner", "interested_space")
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Metric", "Value"])
    for key in (
        "lead_count",
        "viewings",
        "meetings",
        "opportunity_count",
        "offer_sent",
        "won",
        "lost",
        "signed_leases",
        "conversion_lead_to_opp",
        "conversion_opp_to_offer",
        "conversion_offer_to_signed",
    ):
        ws.append([key, report[key]])

    ws2 = wb.create_sheet("Leads")
    ws2.append(
        [
            "ID",
            "Company",
            "Contact",
            "Phone",
            "Email",
            "Source",
            "Qualification",
            "Stage",
            "Record",
            "Outcome",
            "Created",
        ]
    )
    for lead in leads.iterator():
        ws2.append(
            [
                lead.pk,
                lead.company_name,
                lead.full_name,
                lead.phone,
                lead.email,
                lead.source,
                lead.qualification,
                lead.pipeline_stage,
                lead.record_status,
                lead.outcome,
                lead.created_at.isoformat() if lead.created_at else "",
            ]
        )

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
