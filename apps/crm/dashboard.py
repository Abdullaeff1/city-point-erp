"""Satış paneli göstəriciləri (rol = sales).

Cari vəziyyət vs dövr hadisələri ayrılır. V1-də won/lost və dönüşüm faizləri
göstərilmir — Opportunity-də etibarlı mərhələ tarixçəsi yoxdur.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from django.db.models import Max, Q, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.crm.access import can_view_crm
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
    PipelineStage,
    Qualification,
    RecordStatus,
)
from apps.leases.models import Lease, LeaseLine, LeaseStatus
from apps.property.models import CommercialStatus, Occupancy, OperationalStatus, Space

# --- Status tərifləri (cari vəziyyət) ---

OPEN_LEAD_RECORD = (RecordStatus.OPEN, RecordStatus.WAITING)
CLOSED_PIPELINE = (PipelineStage.WON, PipelineStage.LOST)

OFFER_PENDING = OfferStatus.PENDING_APPROVAL
OFFER_APPROVED_UNSENT = OfferStatus.APPROVED
OFFER_VALIDITY_STATUSES = (
    OfferStatus.PENDING_APPROVAL,
    OfferStatus.APPROVED,
    OfferStatus.SENT,
    OfferStatus.NEGOTIATION,
)

APP_SALES_WORK = (
    LeaseApplicationStatus.DRAFT,
    LeaseApplicationStatus.RETURNED_FOR_CORRECTION,
)
APP_ACCOUNTANT_QUEUE = (
    LeaseApplicationStatus.SUBMITTED_TO_ACCOUNTING,
    LeaseApplicationStatus.UNDER_REVIEW,
)

ACTIVE_LEASE_HOLD = (LeaseStatus.ACTIVE, LeaseStatus.EXPIRING)

OFFER_EXPIRING_DAYS = 7
CONTACT_STALE_DAYS = 1
ATTENTION_LIMIT = 12

PERIOD_MONTH = "month"
PERIOD_QUARTER = "quarter"
PERIOD_YEAR = "year"
PERIOD_CUSTOM = "custom"


def parse_period(params: dict | None) -> dict[str, Any]:
    """GET params → {key, date_from, date_to, label_key} (local dates, inclusive)."""
    params = params or {}
    today = timezone.localdate()
    key = (params.get("period") or PERIOD_MONTH).strip().lower()
    if key not in {PERIOD_MONTH, PERIOD_QUARTER, PERIOD_YEAR, PERIOD_CUSTOM}:
        key = PERIOD_MONTH

    date_from: date | None = None
    date_to: date | None = today

    if key == PERIOD_MONTH:
        date_from = today.replace(day=1)
    elif key == PERIOD_QUARTER:
        q_month = ((today.month - 1) // 3) * 3 + 1
        date_from = today.replace(month=q_month, day=1)
    elif key == PERIOD_YEAR:
        date_from = today.replace(month=1, day=1)
    else:
        raw_from = params.get("date_from") or ""
        raw_to = params.get("date_to") or ""
        try:
            date_from = date.fromisoformat(str(raw_from)) if raw_from else today.replace(day=1)
        except ValueError:
            date_from = today.replace(day=1)
        try:
            date_to = date.fromisoformat(str(raw_to)) if raw_to else today
        except ValueError:
            date_to = today
        if date_from > date_to:
            date_from, date_to = date_to, date_from

    return {
        "key": key,
        "date_from": date_from,
        "date_to": date_to,
        "choices": [
            (PERIOD_MONTH, _("Bu ay")),
            (PERIOD_QUARTER, _("Bu rüb")),
            (PERIOD_YEAR, _("Bu il")),
            (PERIOD_CUSTOM, _("Xüsusi tarix aralığı")),
        ],
    }


def _aware_range(d_from: date, d_to: date) -> tuple[datetime, datetime]:
    start = timezone.make_aware(datetime.combine(d_from, time.min))
    end = timezone.make_aware(datetime.combine(d_to, time.max))
    return start, end


def open_leads_qs():
    return (
        Lead.objects.filter(record_status__in=OPEN_LEAD_RECORD)
        .exclude(qualification=Qualification.NON_POTENTIAL)
        .exclude(pipeline_stage__in=CLOSED_PIPELINE)
    )


def open_opportunities_qs():
    return Opportunity.objects.filter(status=OpportunityStatus.OPEN)


def _held_space_ids() -> set[int]:
    from_lease = set(
        Lease.objects.filter(status__in=ACTIVE_LEASE_HOLD, space_id__isnull=False).values_list(
            "space_id", flat=True
        )
    )
    from_lines = set(
        LeaseLine.objects.filter(lease__status__in=ACTIVE_LEASE_HOLD).values_list(
            "space_id", flat=True
        )
    )
    return from_lease | from_lines


def available_spaces_qs(*, today: date | None = None):
    """Kommersiya boş + əməliyyat hazır + əlçatanlıq tarixi + aktiv icarə yox."""
    today = today or timezone.localdate()
    held = _held_space_ids()
    qs = Space.objects.filter(
        commercial_status=CommercialStatus.VACANT,
        operational_status=OperationalStatus.AVAILABLE,
    ).filter(Q(availability_date__isnull=True) | Q(availability_date__lte=today))
    conflict_q = Q(occupancy=Occupancy.ACTIVE_LEASE)
    if held:
        conflict_q |= Q(pk__in=held)
    conflicts = qs.filter(conflict_q)
    available = qs.exclude(conflict_q).select_related("floor")
    return available, conflicts


def _url(name: str, **query) -> str:
    base = reverse(name)
    q = {k: v for k, v in query.items() if v not in (None, "")}
    return f"{base}?{urlencode(q)}" if q else base


def _pipeline_strip() -> list[dict]:
    """Mərhələ başına aktiv qeyd sayı (unique deal deyil)."""
    return [
        {
            "key": "leads",
            "label": _("Lidlər"),
            "count": open_leads_qs().count(),
            "url": _url("erp:crm_leads", record_status=RecordStatus.OPEN),
        },
        {
            "key": "opportunities",
            "label": _("İmkanlar"),
            "count": open_opportunities_qs().count(),
            "url": _url("erp:crm_opportunities", status=OpportunityStatus.OPEN),
        },
        {
            "key": "offers",
            "label": _("Təkliflər"),
            "count": Offer.objects.filter(
                status__in=(
                    OfferStatus.DRAFT,
                    OfferStatus.PENDING_APPROVAL,
                    OfferStatus.APPROVED,
                    OfferStatus.SENT,
                    OfferStatus.NEGOTIATION,
                )
            ).count(),
            "url": reverse("erp:crm_offers"),
        },
        {
            "key": "applications",
            "label": _("Müqavilə müraciətləri"),
            "count": LeaseApplication.objects.exclude(
                status__in=(
                    LeaseApplicationStatus.COMPLETED,
                    LeaseApplicationStatus.CANCELLED,
                )
            ).count(),
            "url": reverse("erp:crm_lease_applications"),
        },
    ]


def _contact_attention(*, now, limit: int) -> list[dict]:
    stale_before = now - timedelta(days=CONTACT_STALE_DAYS)
    rows: list[dict] = []

    lead_ids_with_recent = set(
        LeadActivity.objects.filter(
            lead_id__isnull=False,
            occurred_at__gte=stale_before,
        )
        .exclude(activity_type=ActivityType.STATUS_CHANGE)
        .values_list("lead_id", flat=True)
    )
    lead_last = {
        r["lead_id"]: r["last_at"]
        for r in LeadActivity.objects.filter(lead_id__isnull=False)
        .exclude(activity_type=ActivityType.STATUS_CHANGE)
        .values("lead_id")
        .annotate(last_at=Max("occurred_at"))
    }
    for lead in open_leads_qs().order_by("-updated_at")[:80]:
        if lead.pk in lead_ids_with_recent:
            continue
        last_at = lead_last.get(lead.pk)
        name = lead.company_name or lead.full_name or f"Lid #{lead.pk}"
        area = lead.min_area_m2 or lead.max_area_m2
        rows.append(
            {
                "kind": "lead",
                "title": name,
                "stage": lead.get_pipeline_stage_display(),
                "area_m2": area,
                "last_activity_at": last_at,
                "url": reverse("erp:crm_lead_detail", kwargs={"pk": lead.pk}),
            }
        )
        if len(rows) >= limit:
            return rows

    opp_ids_with_recent = set(
        LeadActivity.objects.filter(
            opportunity_id__isnull=False,
            occurred_at__gte=stale_before,
        )
        .exclude(activity_type=ActivityType.STATUS_CHANGE)
        .values_list("opportunity_id", flat=True)
    )
    opp_last = {
        r["opportunity_id"]: r["last_at"]
        for r in LeadActivity.objects.filter(opportunity_id__isnull=False)
        .exclude(activity_type=ActivityType.STATUS_CHANGE)
        .values("opportunity_id")
        .annotate(last_at=Max("occurred_at"))
    }
    for opp in (
        open_opportunities_qs()
        .select_related("lead", "party", "space")
        .order_by("-updated_at")[:80]
    ):
        if opp.pk in opp_ids_with_recent:
            continue
        last_at = opp_last.get(opp.pk)
        title = opp.title
        if opp.lead_id and (opp.lead.company_name or opp.lead.full_name):
            title = f"{opp.lead.company_name or opp.lead.full_name} · {opp.title}"
        rows.append(
            {
                "kind": "opportunity",
                "title": title,
                "stage": opp.get_pipeline_stage_display(),
                "area_m2": opp.expected_area,
                "last_activity_at": last_at,
                "url": reverse("erp:crm_opportunity_detail", kwargs={"pk": opp.pk}),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _offer_attention(*, today: date, limit: int) -> list[dict]:
    rows: list[dict] = []
    seen: set[int] = set()
    expiring_until = today + timedelta(days=OFFER_EXPIRING_DAYS)

    def _add(offer: Offer, reason: str) -> None:
        if offer.pk in seen:
            return
        seen.add(offer.pk)
        ver = offer.current_version
        rows.append(
            {
                "kind": "offer",
                "title": str(offer.party) if offer.party_id else f"Təklif #{offer.pk}",
                "status": offer.get_status_display(),
                "reason": reason,
                "monthly_rent_net": getattr(ver, "monthly_rent_net", None) if ver else None,
                "monthly_rent_gross": getattr(ver, "monthly_rent_gross", None) if ver else None,
                "area_m2": getattr(ver, "area_m2", None) if ver else None,
                "valid_until": offer.valid_until,
                "url": reverse("erp:crm_offer_detail", kwargs={"pk": offer.pk}),
            }
        )

    base = Offer.objects.select_related("party", "current_version", "space").order_by(
        "valid_until", "-updated_at"
    )
    for o in base.filter(status=OFFER_PENDING)[:limit]:
        _add(o, "pending_approval")
    for o in base.filter(status=OFFER_APPROVED_UNSENT, sent_at__isnull=True)[:limit]:
        if len(rows) >= limit:
            break
        _add(o, "approved_unsent")
    for o in base.filter(
        status__in=OFFER_VALIDITY_STATUSES,
        valid_until__isnull=False,
        valid_until__lte=expiring_until,
    )[:limit]:
        if len(rows) >= limit:
            break
        reason = "expired" if o.valid_until < today else "expiring"
        _add(o, reason)
    return rows[:limit]


def _application_attention(*, limit: int) -> list[dict]:
    rows = []
    qs = (
        LeaseApplication.objects.filter(status__in=APP_SALES_WORK)
        .select_related("space", "opportunity", "offer")
        .order_by("-updated_at")[:limit]
    )
    for app in qs:
        company = app.person_name or (
            app.opportunity.title if app.opportunity_id else f"Müraciət #{app.pk}"
        )
        space_label = app.space_label or (app.space.code if app.space_id else "")
        owner_role = (
            "sales"
            if app.status in APP_SALES_WORK
            else "accountant"
        )
        rows.append(
            {
                "kind": "application",
                "title": company,
                "space_label": space_label,
                "status": app.get_status_display(),
                "owner_role": owner_role,
                "url": reverse("erp:crm_lease_application_detail", kwargs={"pk": app.pk}),
            }
        )
    return rows


def _period_events(period: dict) -> dict:
    start, end = _aware_range(period["date_from"], period["date_to"])
    leads_created = Lead.objects.filter(created_at__gte=start, created_at__lte=end).count()
    viewings = LeadActivity.objects.filter(
        activity_type=ActivityType.VIEWING,
        occurred_at__gte=start,
        occurred_at__lte=end,
    ).count()
    offers_sent = Offer.objects.filter(
        sent_at__isnull=False,
        sent_at__gte=start,
        sent_at__lte=end,
    ).count()
    return {
        "leads_created": leads_created,
        "viewings": viewings,
        "offers_sent": offers_sent,
        # completed/signed omitted in v1 — no reliable completed_at
        "show_win_loss": False,
        "show_conversion": False,
    }


def build_sales_dashboard(user, params: dict | None = None) -> dict[str, Any]:
    """Satış paneli context. Ops KPI buraya daxil deyil."""
    if not can_view_crm(user):
        return {"allowed": False}

    params = params or {}
    period = parse_period(params)
    today = timezone.localdate()
    now = timezone.now()

    open_leads = open_leads_qs().count()
    opps = open_opportunities_qs()
    opp_count = opps.count()
    opp_area = opps.aggregate(s=Sum("expected_area"))["s"]

    pending_offers = Offer.objects.filter(status=OFFER_PENDING).count()
    approved_unsent = Offer.objects.filter(
        status=OFFER_APPROVED_UNSENT, sent_at__isnull=True
    ).count()
    expiring_until = today + timedelta(days=OFFER_EXPIRING_DAYS)
    expiring_offers = Offer.objects.filter(
        status__in=OFFER_VALIDITY_STATUSES,
        valid_until__isnull=False,
        valid_until__lte=expiring_until,
    ).count()

    apps_sales = LeaseApplication.objects.filter(status__in=APP_SALES_WORK).count()
    apps_accountant = LeaseApplication.objects.filter(status__in=APP_ACCOUNTANT_QUEUE).count()

    available_qs, conflict_qs = available_spaces_qs(today=today)
    space_count = available_qs.count()
    area_sum = Decimal("0")
    show_spaces_kpi = True
    for s in available_qs:
        val = s.rentable_area_m2 if s.rentable_area_m2 is not None else s.area_m2
        if val is None:
            show_spaces_kpi = False
            break
        area_sum += Decimal(str(val))
    conflict_count = conflict_qs.count()

    return {
        "allowed": True,
        "is_sales_dashboard": True,
        "period": period,
        "kpi": {
            "open_leads": {
                "count": open_leads,
                "url": _url("erp:crm_leads", record_status=RecordStatus.OPEN),
                "hint": "Açıq / gözləntidə, qeyri-potensial və bağlanmış istisna",
            },
            "open_opportunities": {
                "count": opp_count,
                "expected_area_m2": opp_area,
                "url": _url("erp:crm_opportunities", status=OpportunityStatus.OPEN),
                "hint": "Açıq imkanlar",
            },
            "offers_action": {
                "pending_approval": pending_offers,
                "approved_unsent": approved_unsent,
                "expiring": expiring_offers,
                "url_pending": _url("erp:crm_offers", status=OfferStatus.PENDING_APPROVAL),
                "url_approved": _url("erp:crm_offers", status=OfferStatus.APPROVED),
                "hint": "Təsdiq / göndərmə / müddət",
            },
            "applications": {
                "sales_work": apps_sales,
                "accountant_queue": apps_accountant,
                "url": reverse("erp:crm_lease_applications"),
                "url_returned": _url(
                    "erp:crm_lease_applications",
                    status=LeaseApplicationStatus.RETURNED_FOR_CORRECTION,
                ),
                "url_draft": _url(
                    "erp:crm_lease_applications", status=LeaseApplicationStatus.DRAFT
                ),
                "hint": "Satış işi vs mühasib növbəsi (informativ)",
            },
            "available_spaces": {
                "show": show_spaces_kpi,
                "count": space_count if show_spaces_kpi else 0,
                "total_m2": area_sum if show_spaces_kpi else None,
                "conflict_count": conflict_count,
                "incomplete": not show_spaces_kpi,
                "url": reverse("erp:crm_available_spaces"),
                "hint": "Boş + hazır + əlçatan, aktiv icarəsiz",
            },
        },
        "pipeline_steps": _pipeline_strip(),
        "period_events": _period_events(period),
        "attention_contact": _contact_attention(now=now, limit=ATTENTION_LIMIT),
        "attention_offers": _offer_attention(today=today, limit=ATTENTION_LIMIT),
        "attention_applications": _application_attention(limit=ATTENTION_LIMIT),
        "can_approve_offer": False,  # sales never approves from this panel
        "reports_url": reverse("erp:crm_reports"),
    }
