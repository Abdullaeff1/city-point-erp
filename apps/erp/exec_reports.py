"""M11 rəhbərlik hesabatları — domain KPI builders + snapshot + XLSX."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.db.models import Count, Sum
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date


def parse_report_params(query) -> dict:
    """date_from / date_to / company_id from GET; defaults last 30 days."""
    today = timezone.localdate()
    raw_from = (query.get("date_from") or "").strip()
    raw_to = (query.get("date_to") or "").strip()
    date_from = parse_date(raw_from) if raw_from else today - timedelta(days=30)
    date_to = parse_date(raw_to) if raw_to else today
    if not date_from:
        date_from = today - timedelta(days=30)
    if not date_to:
        date_to = today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    company_id = None
    raw_co = (query.get("company_id") or "").strip()
    if raw_co.isdigit():
        company_id = int(raw_co)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "company_id": company_id,
    }


def _party_ids_for_company(company_id: int | None) -> list[int] | None:
    if not company_id:
        return None
    from apps.parties.models import Party

    return list(
        Party.objects.filter(legacy_resident_company_id=company_id).values_list("pk", flat=True)
    )


def build_property_report(params: dict) -> dict:
    from apps.leases.models import Lease, LeaseStatus
    from apps.property.models import CommercialStatus, Space

    spaces = Space.objects.all()
    vacant = spaces.filter(commercial_status=CommercialStatus.VACANT)
    vacant_m2 = sum(float(s.rentable_area_m2 or s.area_m2 or 0) for s in vacant)
    total_m2 = sum(float(s.rentable_area_m2 or s.area_m2 or 0) for s in spaces) or 1.0
    occupied_m2 = max(total_m2 - vacant_m2, 0)
    horizon = params["date_to"] + timedelta(days=90)
    leases = Lease.objects.filter(
        status__in=[LeaseStatus.ACTIVE, LeaseStatus.EXPIRING],
        end_date__isnull=False,
        end_date__gte=params["date_to"],
        end_date__lte=horizon,
    ).select_related("party", "space")
    party_ids = _party_ids_for_company(params.get("company_id"))
    if party_ids is not None:
        leases = leases.filter(party_id__in=party_ids)
    expiring = list(leases.order_by("end_date")[:50])
    return {
        "tab": "property",
        "space_count": spaces.count(),
        "vacant_count": vacant.count(),
        "vacant_m2": round(vacant_m2, 1),
        "occupied_m2": round(occupied_m2, 1),
        "occupancy_pct": round(100 * occupied_m2 / total_m2, 1),
        "leases_expiring": expiring,
        "leases_expiring_count": len(expiring),
    }


def build_fm_report(params: dict) -> dict:
    from apps.maintenance.models import MaintenancePlan, WorkOrder, WorkOrderStatus
    from apps.property.models import BuildingAssetEvent, BuildingAssetEventType

    open_statuses = (
        WorkOrderStatus.OPEN,
        WorkOrderStatus.ASSIGNED,
        WorkOrderStatus.IN_PROGRESS,
    )
    open_wo = WorkOrder.objects.filter(status__in=open_statuses)
    overdue_pm = MaintenancePlan.objects.filter(
        is_active=True, next_due__isnull=False, next_due__lt=params["date_to"]
    )
    # Təkrar nasazlıq: eyni aktivdə intervalda ≥2 repair event
    repairs = (
        BuildingAssetEvent.objects.filter(
            event_type=BuildingAssetEventType.REPAIR,
            occurred_at__date__gte=params["date_from"],
            occurred_at__date__lte=params["date_to"],
        )
        .values("asset_id")
        .annotate(c=Count("id"))
        .filter(c__gte=2)
    )
    recent_events = (
        BuildingAssetEvent.objects.select_related("asset")
        .filter(occurred_at__date__gte=params["date_from"], occurred_at__date__lte=params["date_to"])
        .order_by("-occurred_at")[:40]
    )
    return {
        "tab": "fm",
        "open_wo": open_wo.count(),
        "overdue_pm": overdue_pm.count(),
        "repeat_repair_assets": repairs.count(),
        "asset_events": list(recent_events),
        "overdue_plans": list(overdue_pm.select_related("building_asset")[:30]),
    }


def build_warehouse_report(params: dict) -> dict:
    from apps.procurement.models import PurchaseOrder, PurchaseRequest
    from apps.warehouse.models import Stock, StockMovement, StockMovementType

    low = [
        st
        for st in Stock.objects.select_related("sku")
        if st.quantity <= (st.sku.reorder_level or 0)
    ]
    issues = StockMovement.objects.filter(
        movement_type=StockMovementType.ISSUE,
        created_at__date__gte=params["date_from"],
        created_at__date__lte=params["date_to"],
    )
    issued_qty = issues.aggregate(s=Sum("quantity"))["s"] or Decimal("0")
    pr_by_status = list(
        PurchaseRequest.objects.values("status").annotate(c=Count("id")).order_by("status")
    )
    po_by_status = list(
        PurchaseOrder.objects.values("status").annotate(c=Count("id")).order_by("status")
    )
    suppliers = list(
        PurchaseOrder.objects.exclude(supplier_party_id=None)
        .values("supplier_party__legal_name")
        .annotate(c=Count("id"))
        .order_by("-c")[:15]
    )
    return {
        "tab": "warehouse",
        "low_stock_count": len(low),
        "low_stock": low[:30],
        "issued_qty": issued_qty,
        "issue_movements": issues.count(),
        "pr_by_status": pr_by_status,
        "po_by_status": po_by_status,
        "top_suppliers": suppliers,
    }


def build_finance_report(params: dict) -> dict:
    from apps.billing.models import Invoice, InvoiceStatus, Payment
    from apps.billing.services import invoice_balance

    inv_qs = Invoice.objects.filter(
        issue_date__gte=params["date_from"],
        issue_date__lte=params["date_to"],
    ).exclude(status=InvoiceStatus.VOID)
    party_ids = _party_ids_for_company(params.get("company_id"))
    if party_ids is not None:
        inv_qs = inv_qs.filter(party_id__in=party_ids)

    invoiced = inv_qs.aggregate(s=Sum("total"))["s"] or Decimal("0")
    payments = Payment.objects.filter(
        paid_at__gte=params["date_from"],
        paid_at__lte=params["date_to"],
    )
    if party_ids is not None:
        payments = payments.filter(party_id__in=party_ids)
    paid = payments.aggregate(s=Sum("amount"))["s"] or Decimal("0")

    open_inv = Invoice.objects.filter(
        status__in=(InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE)
    )
    if party_ids is not None:
        open_inv = open_inv.filter(party_id__in=party_ids)
    overdue = open_inv.filter(status=InvoiceStatus.OVERDUE)
    ar_total = Decimal("0")
    overdue_total = Decimal("0")
    for inv in open_inv.select_related("party"):
        bal = invoice_balance(inv)
        if bal <= 0:
            continue
        ar_total += bal
        if inv.status == InvoiceStatus.OVERDUE:
            overdue_total += bal
    return {
        "tab": "finance",
        "invoiced": invoiced,
        "paid": paid,
        "ar_open": ar_total,
        "overdue_amount": overdue_total,
        "overdue_count": overdue.count(),
        "invoice_count": inv_qs.count(),
    }


def build_security_report(params: dict) -> dict:
    from apps.comms.models import Notification
    from apps.integrations.axtrax_health import axtrax_sync_health
    from apps.residents.models import AccessEvent

    health = axtrax_sync_health()
    events = AccessEvent.objects.filter(
        occurred_at__date__gte=params["date_from"],
        occurred_at__date__lte=params["date_to"],
    )
    if params.get("company_id"):
        events = events.filter(company_id=params["company_id"])
    notifies = Notification.objects.filter(
        created_at__date__gte=params["date_from"],
        created_at__date__lte=params["date_to"],
    )
    return {
        "tab": "security",
        "health": health,
        "access_events": events.count(),
        "notifications": notifies.count(),
        "unread_notifications": notifies.filter(is_read=False).count(),
    }


def build_service_desk_summary(params: dict, *, user=None) -> dict:
    from apps.tickets.access import tickets_visible_to
    from apps.tickets.models import CLOSED_STATUSES, OPEN_STATUSES
    from apps.tickets.reporting import build_sla_report

    days = max(1, (params["date_to"] - params["date_from"]).days + 1)
    qs = tickets_visible_to(user) if user is not None else None
    report = build_sla_report(queryset=qs, days=min(days, 365))
    # Overlay company filter on volume if requested
    if params.get("company_id") and qs is not None:
        scoped = qs.filter(
            company_id=params["company_id"],
            created_at__date__gte=params["date_from"],
            created_at__date__lte=params["date_to"],
        )
        report["company_ticket_count"] = scoped.count()
        report["company_open"] = scoped.filter(status__in=OPEN_STATUSES).count()
        report["company_closed"] = scoped.filter(status__in=CLOSED_STATUSES).count()
    return {**report, "tab": "service_desk"}


def build_exec_bundle(params: dict, *, user=None) -> dict:
    """All domain sections for hub + snapshot payload."""
    from apps.crm.reports import build_crm_funnel_report, build_sales_report

    crm_params = {
        "date_from": params["date_from"],
        "date_to": params["date_to"],
    }
    return {
        "params": {
            "date_from": str(params["date_from"]),
            "date_to": str(params["date_to"]),
            "company_id": params.get("company_id"),
        },
        "property": build_property_report(params),
        "crm": build_crm_funnel_report(crm_params),
        "sales": build_sales_report(crm_params),
        "service_desk": build_service_desk_summary(params, user=user),
        "fm": build_fm_report(params),
        "warehouse": build_warehouse_report(params),
        "finance": build_finance_report(params),
        "security": build_security_report(params),
        "generated_at": timezone.now().isoformat(),
    }


def snapshot_payload_compact(bundle: dict) -> dict:
    """Store scalars only — not a DB backup dump."""
    prop = bundle["property"]
    fin = bundle["finance"]
    fm = bundle["fm"]
    wh = bundle["warehouse"]
    sec = bundle["security"]
    sd = bundle["service_desk"]
    crm = bundle["crm"]
    sales = bundle["sales"]
    return {
        "property": {
            "occupancy_pct": prop["occupancy_pct"],
            "vacant_m2": prop["vacant_m2"],
            "leases_expiring_count": prop["leases_expiring_count"],
        },
        "crm": {
            "lead_count": crm.get("lead_count"),
            "potential": crm.get("potential"),
            "response_coverage_pct": crm.get("response_coverage_pct"),
        },
        "sales": {
            "opportunity_count": sales.get("opportunity_count"),
            "offer_sent": sales.get("offer_sent"),
            "signed_leases": sales.get("signed_leases"),
            "applications": sales.get("applications"),
        },
        "service_desk": {
            "open_risk": sd.get("open_risk"),
            "open_count": sd.get("open_count"),
            "total": sd.get("total"),
            "mttr_avg_hours": sd.get("mttr_avg_hours"),
            "breach_pct": sd.get("breach_pct"),
        },
        "fm": {
            "open_wo": fm["open_wo"],
            "overdue_pm": fm["overdue_pm"],
            "repeat_repair_assets": fm["repeat_repair_assets"],
        },
        "warehouse": {
            "low_stock_count": wh["low_stock_count"],
            "issued_qty": str(wh["issued_qty"]),
            "pr_by_status": wh["pr_by_status"],
            "po_by_status": wh["po_by_status"],
        },
        "finance": {
            "invoiced": str(fin["invoiced"]),
            "paid": str(fin["paid"]),
            "ar_open": str(fin["ar_open"]),
            "overdue_amount": str(fin["overdue_amount"]),
        },
        "security": {
            "events_ok": sec["health"].get("events_ok"),
            "access_events": sec["access_events"],
            "notifications": sec["notifications"],
        },
    }


def capture_daily_snapshot(*, as_of: date | None = None, company_id: int | None = None):
    """Persist KPI snapshot for historical reporting (not backup)."""
    from apps.core.models import ReportSnapshot

    as_of = as_of or timezone.localdate()
    params = {
        "date_from": as_of - timedelta(days=30),
        "date_to": as_of,
        "company_id": company_id,
    }
    bundle = build_exec_bundle(params, user=None)
    payload = snapshot_payload_compact(bundle)
    obj, _ = ReportSnapshot.objects.update_or_create(
        snapshot_date=as_of,
        company_id=company_id,
        defaults={"payload": payload},
    )
    return obj


def exec_report_xlsx_response(bundle: dict) -> HttpResponse:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Exec"
    ws.append(["Section", "Metric", "Value"])
    compact = snapshot_payload_compact(bundle)
    for section, metrics in compact.items():
        if not isinstance(metrics, dict):
            continue
        for key, val in metrics.items():
            if isinstance(val, (list, dict)):
                val = str(val)
            ws.append([section, key, val])
    bio = BytesIO()
    wb.save(bio)
    resp = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = 'attachment; filename="exec_report.xlsx"'
    return resp
