"""CRM vs Satış report metrics + XLSX export helpers."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from django.db.models import Count, Q, Sum
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
    Qualification,
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


def _scoped_opps(params: dict, lead_ids: list[int]):
    opps = Opportunity.objects.filter(Q(lead_id__in=lead_ids) | Q(lead__isnull=True))
    if params.get("date_from"):
        opps = opps.filter(created_at__date__gte=params["date_from"])
    if params.get("date_to"):
        opps = opps.filter(created_at__date__lte=params["date_to"])
    return opps


def build_crm_funnel_report(params: dict | None = None) -> dict:
    """CRM tab: mənbə / kvalifikasiya / cavab müddəti KPI."""
    params = params or {}
    leads = filtered_leads(params)
    lead_ids = list(leads.values_list("pk", flat=True))
    source_breakdown = list(
        leads.values("source").annotate(c=Count("id")).order_by("-c")
    )
    qual_breakdown = list(
        leads.values("qualification").annotate(c=Count("id")).order_by("-c")
    )
    outcome_breakdown = list(
        leads.exclude(outcome="").values("outcome").annotate(c=Count("id")).order_by("-c")
    )
    potential = leads.filter(qualification=Qualification.POTENTIAL).count()
    non_potential = leads.filter(qualification=Qualification.NON_POTENTIAL).count()
    with_activity = (
        LeadActivity.objects.filter(lead_id__in=lead_ids)
        .exclude(activity_type=ActivityType.STATUS_CHANGE)
        .values("lead_id")
        .distinct()
        .count()
    )
    lead_count = leads.count()

    def _pct(num, den):
        return round((num / den) * 100, 1) if den else 0.0

    return {
        "tab": "crm",
        "lead_count": lead_count,
        "potential": potential,
        "non_potential": non_potential,
        "with_first_activity": with_activity,
        "response_coverage_pct": _pct(with_activity, lead_count),
        "source_breakdown": source_breakdown,
        "qualification_breakdown": qual_breakdown,
        "outcome_breakdown": outcome_breakdown,
        "generated_at": timezone.now(),
    }


def build_sales_report(params: dict | None = None) -> dict:
    """Satış tab: imkan / baxış / təklif / müraciət / imza / m² / AZN."""
    params = params or {}
    leads = filtered_leads(params)
    lead_ids = list(leads.values_list("pk", flat=True))
    opps = _scoped_opps(params, lead_ids)
    offers = Offer.objects.filter(opportunity__in=opps)
    apps = LeaseApplication.objects.filter(opportunity__in=opps)

    viewings = LeadActivity.objects.filter(
        Q(lead_id__in=lead_ids) | Q(opportunity__in=opps),
        activity_type=ActivityType.VIEWING,
    ).count()
    meetings = LeadActivity.objects.filter(
        Q(lead_id__in=lead_ids) | Q(opportunity__in=opps),
        activity_type=ActivityType.MEETING,
    ).count()

    offer_sent = offers.filter(
        status__in=(OfferStatus.SENT, OfferStatus.ACCEPTED, OfferStatus.NEGOTIATION)
    ).count()
    apps_count = apps.exclude(status=LeaseApplicationStatus.CANCELLED).count()
    signed = apps.filter(
        status__in=(
            LeaseApplicationStatus.SIGNED_DOCUMENTS_RECEIVED,
            LeaseApplicationStatus.COMPLETED,
        )
    ).count()
    won = opps.filter(status=OpportunityStatus.WON).count()
    lost = opps.filter(status=OpportunityStatus.LOST).count()

    area_agg = offers.filter(
        status__in=(OfferStatus.SENT, OfferStatus.ACCEPTED),
        current_version__isnull=False,
    ).aggregate(total_m2=Sum("current_version__area_m2"), total_azn=Sum("rent_amount"))
    total_m2 = area_agg["total_m2"] or Decimal("0")
    total_azn = area_agg["total_azn"] or Decimal("0")

    def _pct(num, den):
        return round((num / den) * 100, 1) if den else 0.0

    opp_count = opps.count()
    return {
        "tab": "sales",
        "opportunity_count": opp_count,
        "viewings": viewings,
        "meetings": meetings,
        "offer_sent": offer_sent,
        "applications": apps_count,
        "signed_leases": signed,
        "won": won,
        "lost": lost,
        "total_m2": total_m2,
        "total_azn": total_azn,
        "conversion_lead_to_opp": _pct(opp_count, leads.count()),
        "conversion_opp_to_offer": _pct(offer_sent, opp_count),
        "conversion_offer_to_signed": _pct(signed, offer_sent or offers.count()),
        "generated_at": timezone.now(),
    }


def build_crm_report(params: dict | None = None) -> dict:
    """Legacy combined payload (CRM + Satış metrics) for older callers/tests."""
    params = params or {}
    crm = build_crm_funnel_report(params)
    sales = build_sales_report(params)
    return {
        **{k: v for k, v in crm.items() if k != "tab"},
        **{k: v for k, v in sales.items() if k not in ("tab", "generated_at")},
        "stage_breakdown": list(
            filtered_leads(params).values("pipeline_stage").annotate(c=Count("id")).order_by("-c")
        ),
        "generated_at": timezone.now(),
    }


def export_crm_xlsx(params: dict | None = None, *, tab: str = "crm") -> bytes:
    from openpyxl import Workbook

    params = params or {}
    wb = Workbook()
    ws = wb.active
    if tab == "sales":
        report = build_sales_report(params)
        ws.title = "Sales"
        ws.append(["Metric", "Value"])
        for key in (
            "opportunity_count",
            "viewings",
            "meetings",
            "offer_sent",
            "applications",
            "signed_leases",
            "won",
            "lost",
            "total_m2",
            "total_azn",
            "conversion_lead_to_opp",
            "conversion_opp_to_offer",
            "conversion_offer_to_signed",
        ):
            ws.append([key, str(report.get(key, ""))])
    else:
        report = build_crm_funnel_report(params)
        ws.title = "CRM"
        ws.append(["Metric", "Value"])
        for key in (
            "lead_count",
            "potential",
            "non_potential",
            "with_first_activity",
            "response_coverage_pct",
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
        for lead in filtered_leads(params).iterator():
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
        ws3 = wb.create_sheet("Sources")
        ws3.append(["Source", "Count"])
        for row in report["source_breakdown"]:
            ws3.append([row["source"], row["c"]])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
