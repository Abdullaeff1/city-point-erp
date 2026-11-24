"""Phase 13 / M11 rəhbərlik hesabatları — domain KPI + as-of + XLSX.

Timezone: Django TIME_ZONE (Asia/Baku). date_to = as-of for state metrics;
date_from..date_to = activity window. UI interpretation for GL: posted JE
entry_date ≤ as_of (effective date), not “what we knew that calendar day”.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.db.models import Count, Prefetch, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date

# Lease statuses that can commercially bind a space
_LEASE_BIND_STATUSES = (
    "signed",
    "active",
    "expiring",
    "renewed",
    "amended",
)


def parse_report_params(query) -> dict:
    """date_from / date_to / company_id from GET; defaults last 30 days.

    date_to is the as-of cutoff for state metrics (occupancy, AR, open WO).
    """
    today = timezone.localdate()
    raw_from = (query.get("date_from") or "").strip()
    raw_to = (query.get("date_to") or query.get("as_of") or "").strip()
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
    page = 1
    raw_page = (query.get("page") or "").strip()
    if raw_page.isdigit():
        page = max(1, int(raw_page))
    return {
        "date_from": date_from,
        "date_to": date_to,
        "as_of": date_to,
        "company_id": company_id,
        "page": page,
        "page_size": 100,
    }


def _party_ids_for_company(company_id: int | None) -> list[int] | None:
    if not company_id:
        return None
    from apps.parties.models import Party

    return list(
        Party.objects.filter(legacy_resident_company_id=company_id).values_list("pk", flat=True)
    )


def _space_m2(space) -> Decimal:
    return Decimal(str(space.rentable_area_m2 or space.area_m2 or 0))


def build_property_report(params: dict) -> dict:
    """Occupancy as of date_to from lease effective dates (not today's commercial flag alone).

    Denominator: rentable m² of spaces that are not operationally BLOCKED and m² > 0.
    Occupied: binding lease with start_date ≤ as_of and (no end or end ≥ as_of).
    Reserved: binding lease with start_date > as_of (future-start signed/active).
    Available: denominator − occupied − reserved.
    One space counted once (occupied wins over reserved).
    """
    from apps.leases.models import Lease
    from apps.property.models import OperationalStatus, Space

    as_of = params["date_to"]
    spaces = list(Space.objects.select_related("floor", "floor__building").all())
    denom = []
    excluded_non_rentable = 0
    excluded_blocked = 0
    for s in spaces:
        if s.operational_status == OperationalStatus.BLOCKED:
            excluded_blocked += 1
            continue
        m2 = _space_m2(s)
        if m2 <= 0:
            excluded_non_rentable += 1
            continue
        denom.append(s)
    denom_ids = {s.pk for s in denom}
    total_m2 = sum((_space_m2(s) for s in denom), Decimal("0"))

    leases = (
        Lease.objects.filter(status__in=_LEASE_BIND_STATUSES, space_id__isnull=False)
        .exclude(start_date__isnull=True)
        .select_related("space", "party", "party__legacy_resident_company")
    )
    party_ids = _party_ids_for_company(params.get("company_id"))
    if party_ids is not None:
        leases = leases.filter(party_id__in=party_ids)

    occupied: dict[int, dict] = {}
    reserved: dict[int, dict] = {}
    skipped_not_yet_recorded = 0
    for lease in leases:
        sid = lease.space_id
        if sid not in denom_ids:
            continue
        # Hold becomes visible only after the lease row was recorded (created_at).
        # Without that, as-of before the reservation cannot be reconstructed from
        # a later-created lease alone — we skip and surface the rule.
        hold_recorded = (
            lease.created_at.date() if getattr(lease, "created_at", None) else None
        )
        if hold_recorded is not None and hold_recorded > as_of:
            skipped_not_yet_recorded += 1
            continue
        end = lease.end_date
        if end is not None and end < as_of:
            continue
        start = lease.start_date
        company_id = None
        if lease.party_id and getattr(lease.party, "legacy_resident_company_id", None):
            company_id = lease.party.legacy_resident_company_id
        row = {
            "space_id": sid,
            "space_code": lease.space.code if lease.space_id else "",
            "lease_code": lease.code,
            "party": lease.party.legal_name if lease.party_id else "",
            "party_id": lease.party_id,
            "company_id": company_id,
            "start_date": start,
            "end_date": end,
            "hold_recorded": hold_recorded,
            "m2": float(_space_m2(lease.space)),
            "status": lease.status,
        }
        if start > as_of:
            # Future-start: commercially held, not yet physically occupied
            if sid not in occupied:
                reserved[sid] = row
        else:
            occupied[sid] = row
            reserved.pop(sid, None)

    occupied_m2 = sum((Decimal(str(r["m2"])) for r in occupied.values()), Decimal("0"))
    reserved_m2 = sum((Decimal(str(r["m2"])) for r in reserved.values()), Decimal("0"))
    available_ids = denom_ids - set(occupied) - set(reserved)
    available_m2 = sum(
        (_space_m2(s) for s in denom if s.pk in available_ids), Decimal("0")
    )

    if total_m2 <= 0:
        occupancy_pct = None
        occupancy_display = "—"
    else:
        occupancy_pct = round(float(100 * occupied_m2 / total_m2), 1)
        occupancy_display = f"{occupancy_pct}%"

    horizon = as_of + timedelta(days=90)
    expiring = list(
        Lease.objects.filter(
            status__in=("active", "expiring"),
            end_date__isnull=False,
            end_date__gte=as_of,
            end_date__lte=horizon,
        )
        .select_related("party", "space")
        .order_by("end_date")[:50]
    )
    if party_ids is not None:
        expiring = [l for l in expiring if l.party_id in party_ids]

    return {
        "tab": "property",
        "as_of": as_of,
        "rule": (
            "İcarə start/end ≤ as_of → dolu; gələcək start → rezerv; "
            "hold yalnız lease.created_at ≤ as_of olduqda; "
            "məxrəc = bloklanmamış rentable m²"
        ),
        "skipped_not_yet_recorded": skipped_not_yet_recorded,
        "space_count": len(spaces),
        "denominator_count": len(denom),
        "total_m2": float(total_m2),
        "occupied_count": len(occupied),
        "occupied_m2": float(occupied_m2),
        "reserved_count": len(reserved),
        "reserved_m2": float(reserved_m2),
        "available_count": len(available_ids),
        "available_m2": float(available_m2),
        "vacant_count": len(available_ids),  # alias for legacy templates
        "vacant_m2": float(available_m2),
        "occupancy_pct": occupancy_pct if occupancy_pct is not None else 0.0,
        "occupancy_display": occupancy_display,
        "occupancy_unavailable": total_m2 <= 0,
        "excluded_blocked": excluded_blocked,
        "excluded_non_rentable": excluded_non_rentable,
        "occupied_rows": list(occupied.values()),
        "reserved_rows": list(reserved.values()),
        "available_rows": [
            {
                "space_id": s.pk,
                "space_code": s.code,
                "m2": float(_space_m2(s)),
            }
            for s in denom
            if s.pk in available_ids
        ],
        # Inventory rows for Management building cards (count ≠ m²)
        "denominator_ids": sorted(denom_ids),
        "denominator_rows": [
            {
                "space_id": s.pk,
                "space_code": s.code,
                "m2": float(_space_m2(s)),
            }
            for s in denom
        ],
        "occupying_company_ids": sorted(
            {r["company_id"] for r in occupied.values() if r.get("company_id")}
        ),
        "occupying_company_count": len(
            {r["company_id"] for r in occupied.values() if r.get("company_id")}
        ),
        "leases_expiring": expiring,
        "leases_expiring_count": len(expiring),
        "history_note": (
            "Keçmiş tarix lease start/end + created_at (hold qeydi) ilə yenidən qurulur. "
            "created_at-dən əvvəlki «boş» vəziyyət yalnız o tarixdə snapshot varsa "
            "«nə göründü» kimi oxuna bilər."
        ),
        "reconstruction_limit": (
            "Snapshot yoxdursa panel reconstruction göstərir; "
            "onu həmin günkü idarəetmə görünüşü kimi təqdim etmir."
        ),
    }


def build_fm_report(params: dict) -> dict:
    """WO open-as-of cutoff + aging buckets; closed-after-cutoff still counted open historically."""
    from apps.maintenance.models import MaintenancePlan, WorkOrder, WorkOrderStatus
    from apps.property.models import BuildingAssetEvent, BuildingAssetEventType

    as_of = params["date_to"]
    open_live = (
        WorkOrderStatus.OPEN,
        WorkOrderStatus.ASSIGNED,
        WorkOrderStatus.IN_PROGRESS,
    )
    # Historical open: created on/before as_of; not completed on/before as_of
    open_as_of_qs = (
        WorkOrder.objects.filter(created_at__date__lte=as_of)
        .filter(Q(completed_at__isnull=True) | Q(completed_at__date__gt=as_of))
        .exclude(status=WorkOrderStatus.CANCELLED)
        .select_related("space", "party")
    )
    buckets = {"0_7": [], "8_30": [], "31_60": [], "60_plus": []}
    for wo in open_as_of_qs[:500]:
        age = (as_of - wo.created_at.date()).days
        row = {
            "id": wo.pk,
            "code": wo.code,
            "title": wo.title,
            "status": wo.status,
            "created_at": wo.created_at,
            "completed_at": wo.completed_at,
            "age_days": age,
        }
        if age <= 7:
            buckets["0_7"].append(row)
        elif age <= 30:
            buckets["8_30"].append(row)
        elif age <= 60:
            buckets["31_60"].append(row)
        else:
            buckets["60_plus"].append(row)

    overdue_pm = MaintenancePlan.objects.filter(
        is_active=True, next_due__isnull=False, next_due__lt=as_of
    )
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
        .filter(
            occurred_at__date__gte=params["date_from"],
            occurred_at__date__lte=params["date_to"],
        )
        .order_by("-occurred_at")[:40]
    )
    open_count = open_as_of_qs.count()
    # Drill list: same QS as count (not the 500 aging sample). Paginate for UI.
    page_size = int(params.get("page_size") or 100)
    page = max(1, int(params.get("page") or 1))
    offset = (page - 1) * page_size
    open_wo_page = list(
        open_as_of_qs.order_by("created_at", "id")[offset : offset + page_size]
    )
    open_wo_rows = [
        {
            "id": wo.pk,
            "code": wo.code,
            "title": wo.title,
            "status": wo.status,
            "created_at": wo.created_at,
            "completed_at": wo.completed_at,
            "age_days": (as_of - wo.created_at.date()).days,
        }
        for wo in open_wo_page
    ]
    return {
        "tab": "fm",
        "as_of": as_of,
        "rule": "Açıq = created≤as_of və (completed yox və ya completed>as_of); ləğv istisna",
        "open_wo": open_count,
        "open_wo_live": WorkOrder.objects.filter(status__in=open_live).count(),
        "open_wo_rows": open_wo_rows,
        "open_wo_page": page,
        "open_wo_page_size": page_size,
        "open_wo_has_more": offset + len(open_wo_rows) < open_count,
        "aging": {k: len(v) for k, v in buckets.items()},
        "aging_rows": buckets,
        "overdue_pm": overdue_pm.count(),
        "repeat_repair_assets": repairs.count(),
        "asset_events": list(recent_events),
        "overdue_plans": list(overdue_pm.select_related("building_asset")[:30]),
        "history_note": "completed_at ilə keçmiş açıqlıq yenidən qurulur.",
        "aging_sample_note": (
            "Aging nümunəsi ≤500 sətir; tam siyahı open_wo_rows / səhifələmə ilə."
            if open_count > 500
            else ""
        ),
    }


def build_warehouse_report(params: dict) -> dict:
    """On-hand / reserved / available by warehouse×SKU; low-stock; issues by unit (no mixed sum)."""
    from apps.procurement.models import PurchaseOrder, PurchaseRequest
    from apps.warehouse.models import Stock, StockMovement, StockMovementType

    stocks = list(Stock.objects.select_related("sku", "warehouse").all())
    low = []
    by_unit: dict[str, dict] = {}
    lines = []
    for st in stocks:
        unit = (st.sku.unit or "pcs").strip() or "pcs"
        on_hand = st.quantity or Decimal("0")
        reserved = st.reserved_quantity or Decimal("0")
        available = st.available_quantity
        reorder = st.sku.reorder_level or Decimal("0")
        row = {
            "warehouse": st.warehouse.code,
            "sku": st.sku.code,
            "unit": unit,
            "on_hand": on_hand,
            "reserved": reserved,
            "available": available,
            "reorder_level": reorder,
            "is_low": on_hand <= reorder,
        }
        lines.append(row)
        bucket = by_unit.setdefault(
            unit,
            {
                "unit": unit,
                "on_hand": Decimal("0"),
                "reserved": Decimal("0"),
                "available": Decimal("0"),
                "low_lines": 0,
            },
        )
        bucket["on_hand"] += on_hand
        bucket["reserved"] += reserved
        bucket["available"] += available
        if row["is_low"]:
            low.append(row)
            bucket["low_lines"] += 1

    issues = StockMovement.objects.filter(
        movement_type=StockMovementType.ISSUE,
        created_at__date__gte=params["date_from"],
        created_at__date__lte=params["date_to"],
    ).select_related("sku")
    issued_by_unit: dict[str, Decimal] = {}
    for mv in issues:
        u = (mv.sku.unit or "pcs").strip() or "pcs"
        issued_by_unit[u] = issued_by_unit.get(u, Decimal("0")) + (mv.quantity or Decimal("0"))

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
    # Legacy scalar: only when a single unit exists; else null (not fake zero)
    issued_qty = None
    if len(issued_by_unit) == 1:
        issued_qty = next(iter(issued_by_unit.values()))
    elif len(issued_by_unit) == 0:
        issued_qty = Decimal("0")

    return {
        "tab": "warehouse",
        "as_of": params["date_to"],
        "rule": "Low-stock = on_hand ≤ SKU.reorder_level (anbar×SKU); vahidlər qarışdırılmır",
        "low_stock_count": len(low),
        "low_stock": low[:40],
        "stock_lines": lines[:100],
        "by_unit": [
            {
                **b,
                "on_hand": b["on_hand"],
                "reserved": b["reserved"],
                "available": b["available"],
            }
            for b in by_unit.values()
        ],
        "issued_qty": issued_qty,
        "issued_by_unit": [{"unit": u, "qty": q} for u, q in sorted(issued_by_unit.items())],
        "issued_mixed_units": len(issued_by_unit) > 1,
        "issue_movements": issues.count(),
        "pr_by_status": pr_by_status,
        "po_by_status": po_by_status,
        "top_suppliers": suppliers,
        "history_note": (
            "Cari on-hand/reserved; tarixi stok üçün stocktake/movement — tam as-of inventar "
            "hələ dəstəklənmir (current-only)."
        ),
        "historical_stock": False,
    }


def build_finance_report(params: dict) -> dict:
    """Operational AR (billing) vs posted AR (GL) as of date_to; activity in range."""
    from apps.accounting.coa import code_for
    from apps.accounting.models import JournalEntry, JournalLine
    from apps.billing.models import Invoice, InvoiceStatus, Payment
    from apps.billing.services import invoice_balance_as_of

    as_of = params["date_to"]
    party_ids = _party_ids_for_company(params.get("company_id"))

    inv_activity = Invoice.objects.filter(
        issue_date__gte=params["date_from"],
        issue_date__lte=params["date_to"],
    ).exclude(status=InvoiceStatus.VOID)
    if party_ids is not None:
        inv_activity = inv_activity.filter(party_id__in=party_ids)
    invoiced = inv_activity.aggregate(s=Sum("total"))["s"] or Decimal("0")

    payments_activity = Payment.objects.filter(
        paid_at__gte=params["date_from"],
        paid_at__lte=params["date_to"],
    )
    if party_ids is not None:
        payments_activity = payments_activity.filter(party_id__in=party_ids)
    paid = payments_activity.aggregate(s=Sum("amount"))["s"] or Decimal("0")

    invoices = (
        Invoice.objects.exclude(status__in=(InvoiceStatus.VOID, InvoiceStatus.DRAFT))
        .filter(issue_date__lte=as_of)
        .prefetch_related(
            Prefetch(
                "payments",
                queryset=Payment.objects.only("amount", "paid_at", "invoice_id"),
            )
        )
        .select_related("party")
    )
    if party_ids is not None:
        invoices = invoices.filter(party_id__in=party_ids)

    operational_ar = Decimal("0")
    overdue_total = Decimal("0")
    overdue_count = 0
    open_rows = []
    for inv in invoices:
        bal = invoice_balance_as_of(inv, as_of)
        if bal <= 0:
            continue
        operational_ar += bal
        due = inv.due_date or inv.issue_date or as_of
        is_overdue = due < as_of
        if is_overdue:
            overdue_total += bal
            overdue_count += 1
        open_rows.append(
            {
                "code": inv.code,
                "party": inv.party.display_name if inv.party_id else "",
                "issue_date": inv.issue_date,
                "due_date": inv.due_date,
                "balance": bal,
                "currency": inv.currency or "AZN",
                "overdue": is_overdue,
            }
        )

    ar_code = code_for("ar")
    ar_lines = JournalLine.objects.filter(
        entry__posted=True,
        entry__entry_date__lte=as_of,
        account__code=ar_code,
    )
    posted_debit = ar_lines.aggregate(s=Sum("debit"))["s"] or Decimal("0")
    posted_credit = ar_lines.aggregate(s=Sum("credit"))["s"] or Decimal("0")
    posted_ar = posted_debit - posted_credit

    unposted_pay = JournalEntry.objects.filter(
        source="billing.payment",
        posted=False,
        entry_date__lte=as_of,
    )
    reconciling_payments = []
    reconciling_total = Decimal("0")
    for je in unposted_pay.prefetch_related("lines__account"):
        amt = sum(
            (ln.credit or Decimal("0") for ln in je.lines.all() if ln.account.code == ar_code),
            Decimal("0"),
        )
        if amt <= 0:
            amt = sum((ln.debit or Decimal("0") for ln in je.lines.all()), Decimal("0"))
        reconciling_total += amt
        reconciling_payments.append(
            {
                "je_code": je.code,
                "source_ref": je.source_ref,
                "entry_date": je.entry_date,
                "amount": amt,
            }
        )

    return {
        "tab": "finance",
        "as_of": as_of,
        "currency": "AZN",
        "rule_operational": "Billing: issue_date≤as_of − payments paid_at≤as_of (DRAFT/VOID yox)",
        "rule_posted": (
            "GL: posted JE, entry_date≤as_of, hesab 110 (AR). "
            "Backdated post effective date-ə düşür; 'həmin gün bilirdik' = snapshot."
        ),
        "invoiced": invoiced,
        "paid": paid,
        "ar_open": operational_ar,
        "operational_ar": operational_ar,
        "posted_ar": posted_ar,
        "overdue_amount": overdue_total,
        "overdue_count": overdue_count,
        "invoice_count": inv_activity.count(),
        "open_rows": open_rows[:100],
        "reconciling_unposted_payments": reconciling_payments[:50],
        "reconciling_unposted_total": reconciling_total,
        "coverage": {
            "receivables_operational": True,
            "receivables_posted": True,
            "ap": False,
            "statutory_vat": False,
            "bank_reconciliation": False,
            "deposit_as_revenue": False,
        },
        "coverage_notes": (
            "AP / statutory ƏDV / bank uzlaşma / depozit öhdəlik — Finance qəbulu gözləyir; "
            "sıfır kimi göstərilmir."
        ),
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
        "privacy_note": "Şəxsi access/guest detalları bu KPI-də yoxdur — mövcud rol sərhədləri.",
    }


def build_service_desk_summary(params: dict, *, user=None) -> dict:
    from apps.tickets.access import tickets_visible_to
    from apps.tickets.models import CLOSED_STATUSES, OPEN_STATUSES
    from apps.tickets.reporting import build_sla_report

    days = max(1, (params["date_to"] - params["date_from"]).days + 1)
    qs = tickets_visible_to(user) if user is not None else None
    report = build_sla_report(queryset=qs, days=min(days, 365))
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
            "as_of": str(params["date_to"]),
            "company_id": params.get("company_id"),
            "timezone": str(timezone.get_current_timezone()),
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
            "occupancy_pct": prop.get("occupancy_pct"),
            "vacant_m2": prop.get("vacant_m2"),
            "reserved_m2": prop.get("reserved_m2"),
            "occupied_m2": prop.get("occupied_m2"),
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
            "aging": fm.get("aging"),
        },
        "warehouse": {
            "low_stock_count": wh["low_stock_count"],
            "issued_qty": str(wh["issued_qty"]) if wh["issued_qty"] is not None else "mixed/n/a",
            "pr_by_status": wh["pr_by_status"],
            "po_by_status": wh["po_by_status"],
        },
        "finance": {
            "invoiced": str(fin["invoiced"]),
            "paid": str(fin["paid"]),
            "ar_open": str(fin["operational_ar"]),
            "posted_ar": str(fin["posted_ar"]),
            "overdue_amount": str(fin["overdue_amount"]),
            "reconciling_unposted_total": str(fin["reconciling_unposted_total"]),
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

    params = bundle.get("params") or {}
    wb = Workbook()
    meta = wb.active
    meta.title = "Meta"
    meta.append(["Field", "Value"])
    meta.append(["timezone", params.get("timezone", "")])
    meta.append(["date_from", params.get("date_from", "")])
    meta.append(["date_to / as_of", params.get("date_to", "")])
    meta.append(["company_id", params.get("company_id") or "all"])
    meta.append(["generated_at", bundle.get("generated_at", "")])
    meta.append(["unit_note", "Mixed warehouse units are not summed"])

    summary = wb.create_sheet("Summary")
    summary.append(["Section", "Metric", "Value", "Unit"])
    compact = snapshot_payload_compact(bundle)
    for section, metrics in compact.items():
        if not isinstance(metrics, dict):
            continue
        for key, val in metrics.items():
            if isinstance(val, (list, dict)):
                val = str(val)
            unit = "AZN" if "ar" in key or key in ("invoiced", "paid", "overdue_amount") else ""
            if "m2" in key:
                unit = "m²"
            if "pct" in key:
                unit = "%"
            summary.append([section, key, val, unit])

    prop = bundle["property"]
    spaces = wb.create_sheet("Occupancy")
    spaces.append(["Bucket", "Space", "Lease", "Party", "m2", "Start", "Status"])
    for r in prop.get("occupied_rows") or []:
        spaces.append(
            ["occupied", r["space_code"], r["lease_code"], r["party"], r["m2"], str(r["start_date"]), r["status"]]
        )
    for r in prop.get("reserved_rows") or []:
        spaces.append(
            ["reserved", r["space_code"], r["lease_code"], r["party"], r["m2"], str(r["start_date"]), r["status"]]
        )
    for r in prop.get("available_rows") or []:
        spaces.append(["available", r["space_code"], "", "", r["m2"], "", ""])

    fin = bundle["finance"]
    ar_sheet = wb.create_sheet("AR")
    ar_sheet.append(
        ["Code", "Party", "Issue", "Due", "Balance", "Currency", "Overdue"]
    )
    for r in fin.get("open_rows") or []:
        ar_sheet.append(
            [
                r["code"],
                r["party"],
                str(r["issue_date"] or ""),
                str(r["due_date"] or ""),
                float(r["balance"]),
                r["currency"],
                r["overdue"],
            ]
        )
    ar_sheet.append([])
    ar_sheet.append(["operational_ar", float(fin["operational_ar"])])
    ar_sheet.append(["posted_ar", float(fin["posted_ar"])])
    ar_sheet.append(["reconciling_unposted", float(fin["reconciling_unposted_total"])])

    wo_sheet = wb.create_sheet("WO_Aging")
    wo_sheet.append(["Bucket", "Code", "Title", "Status", "AgeDays", "Created", "Completed"])
    for bucket, rows in (bundle["fm"].get("aging_rows") or {}).items():
        for r in rows:
            wo_sheet.append(
                [
                    bucket,
                    r["code"],
                    r["title"],
                    r["status"],
                    r["age_days"],
                    str(r["created_at"].date()) if r.get("created_at") else "",
                    str(r["completed_at"].date()) if r.get("completed_at") else "",
                ]
            )

    wh = wb.create_sheet("Stock")
    wh.append(["Warehouse", "SKU", "Unit", "OnHand", "Reserved", "Available", "Reorder", "Low"])
    for r in bundle["warehouse"].get("stock_lines") or []:
        wh.append(
            [
                r["warehouse"],
                r["sku"],
                r["unit"],
                float(r["on_hand"]),
                float(r["reserved"]),
                float(r["available"]),
                float(r["reorder_level"]),
                r["is_low"],
            ]
        )

    bio = BytesIO()
    wb.save(bio)
    resp = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    as_of = params.get("date_to") or timezone.localdate().isoformat()
    resp["Content-Disposition"] = f'attachment; filename="exec_report_{as_of}.xlsx"'
    return resp
