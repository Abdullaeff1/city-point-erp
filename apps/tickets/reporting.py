"""SLA compliance / MTTR helpers for ERP reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO

from django.db.models import Prefetch, QuerySet
from django.http import HttpResponse
from django.utils import timezone

from apps.tickets.business_calendar import business_seconds_between
from apps.tickets.models import CLOSED_STATUSES, OPEN_STATUSES, Ticket, TicketStatusEvent


def _resolve_closed_at(ticket: Ticket) -> datetime | None:
    if ticket.status not in CLOSED_STATUSES:
        return None
    event = (
        ticket.status_events.filter(to_status__in=list(CLOSED_STATUSES))
        .order_by("-created_at")
        .first()
    )
    return event.created_at if event else ticket.updated_at


def ticket_resolution_business_hours(ticket: Ticket) -> float | None:
    closed_at = _resolve_closed_at(ticket)
    if not closed_at:
        return None
    secs = business_seconds_between(ticket.created_at, closed_at)
    return round(max(secs, 0) / 3600.0, 2)


def was_breached_at_close(ticket: Ticket) -> bool | None:
    """Whether ticket was past sla_due when closed (approx)."""
    if not ticket.sla_due_at:
        return None
    closed_at = _resolve_closed_at(ticket)
    if not closed_at:
        return None
    return closed_at > ticket.sla_due_at and not ticket.sla_paused_at


def build_sla_report(*, queryset: QuerySet[Ticket] | None = None, days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=days)
    qs = queryset if queryset is not None else Ticket.objects.all()
    qs = (
        qs.filter(created_at__gte=since)
        .select_related("department", "company")
        .prefetch_related(
            Prefetch(
                "status_events",
                queryset=TicketStatusEvent.objects.order_by("created_at"),
            )
        )
    )
    tickets = list(qs[:2000])

    open_tickets = [t for t in tickets if t.status in OPEN_STATUSES]
    closed = [t for t in tickets if t.status in CLOSED_STATUSES]
    open_risk = sum(1 for t in open_tickets if t.sla_risk)
    open_breach = sum(1 for t in open_tickets if t.sla_breached)
    escalated = sum(1 for t in tickets if (t.escalation_level or 0) > 0)

    mttr_values = []
    closed_breached = 0
    closed_with_sla = 0
    by_dept: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "closed": 0, "mttr_sum": 0.0, "mttr_n": 0, "breached": 0}
    )
    by_priority: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "closed": 0, "mttr_sum": 0.0, "mttr_n": 0, "breached": 0}
    )

    rows = []
    for t in tickets:
        dept_name = t.department.name if t.department_id else "—"
        by_dept[dept_name]["count"] += 1
        by_priority[t.priority]["count"] += 1
        hours = ticket_resolution_business_hours(t)
        breached_close = was_breached_at_close(t)
        if t.status in CLOSED_STATUSES:
            by_dept[dept_name]["closed"] += 1
            by_priority[t.priority]["closed"] += 1
            if hours is not None:
                mttr_values.append(hours)
                by_dept[dept_name]["mttr_sum"] += hours
                by_dept[dept_name]["mttr_n"] += 1
                by_priority[t.priority]["mttr_sum"] += hours
                by_priority[t.priority]["mttr_n"] += 1
            if t.sla_due_at:
                closed_with_sla += 1
                if breached_close:
                    closed_breached += 1
                    by_dept[dept_name]["breached"] += 1
                    by_priority[t.priority]["breached"] += 1
        rows.append(
            {
                "code": t.code,
                "company": t.company.name if t.company_id else "",
                "department": dept_name,
                "priority": t.get_priority_display(),
                "status": t.get_status_display(),
                "created_at": t.created_at,
                "sla_due_at": t.sla_due_at,
                "resolution_hours": hours,
                "escalation_level": t.escalation_level or 0,
                "open_risk": bool(t.status in OPEN_STATUSES and t.sla_risk),
                "open_breach": bool(t.status in OPEN_STATUSES and t.sla_breached),
            }
        )

    def _avg(bucket):
        n = bucket["mttr_n"]
        return round(bucket["mttr_sum"] / n, 2) if n else None

    dept_rows = [
        {
            "name": name,
            "count": b["count"],
            "closed": b["closed"],
            "mttr": _avg(b),
            "breached": b["breached"],
        }
        for name, b in sorted(by_dept.items(), key=lambda x: -x[1]["count"])
    ]
    priority_rows = [
        {
            "name": Ticket(priority=code).get_priority_display() if code else code,
            "code": code,
            "count": b["count"],
            "closed": b["closed"],
            "mttr": _avg(b),
            "breached": b["breached"],
        }
        for code, b in sorted(by_priority.items())
    ]

    mttr_avg = round(sum(mttr_values) / len(mttr_values), 2) if mttr_values else None
    breach_pct = (
        round(100.0 * closed_breached / closed_with_sla, 1) if closed_with_sla else None
    )

    return {
        "days": days,
        "total": len(tickets),
        "open_count": len(open_tickets),
        "closed_count": len(closed),
        "open_risk": open_risk,
        "open_breach": open_breach,
        "escalated": escalated,
        "mttr_avg_hours": mttr_avg,
        "breach_pct": breach_pct,
        "closed_with_sla": closed_with_sla,
        "closed_breached": closed_breached,
        "by_department": dept_rows,
        "by_priority": priority_rows,
        "rows": rows,
    }


def sla_report_xlsx_http_response(report: dict) -> HttpResponse:
    from openpyxl import Workbook

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary.append(["Metric", "Value"])
    summary.append(["Period days", report["days"]])
    summary.append(["Total tickets", report["total"]])
    summary.append(["Open", report["open_count"]])
    summary.append(["Closed", report["closed_count"]])
    summary.append(["Open SLA risk", report["open_risk"]])
    summary.append(["Open SLA breach", report["open_breach"]])
    summary.append(["Escalated", report["escalated"]])
    summary.append(["MTTR (business hours)", report["mttr_avg_hours"]])
    summary.append(["Closed breach %", report["breach_pct"]])

    dept = wb.create_sheet("By department")
    dept.append(["Department", "Count", "Closed", "MTTR h", "Breached"])
    for row in report["by_department"]:
        dept.append([row["name"], row["count"], row["closed"], row["mttr"], row["breached"]])

    pri = wb.create_sheet("By priority")
    pri.append(["Priority", "Count", "Closed", "MTTR h", "Breached"])
    for row in report["by_priority"]:
        pri.append([row["name"], row["count"], row["closed"], row["mttr"], row["breached"]])

    detail = wb.create_sheet("Tickets")
    detail.append(
        [
            "Code",
            "Company",
            "Department",
            "Priority",
            "Status",
            "Created",
            "SLA due",
            "Resolution h",
            "Escalation",
            "Open risk",
            "Open breach",
        ]
    )
    for row in report["rows"]:
        detail.append(
            [
                row["code"],
                row["company"],
                row["department"],
                row["priority"],
                row["status"],
                row["created_at"].isoformat(sep=" ", timespec="minutes") if row["created_at"] else "",
                row["sla_due_at"].isoformat(sep=" ", timespec="minutes") if row["sla_due_at"] else "",
                row["resolution_hours"],
                row["escalation_level"],
                "yes" if row["open_risk"] else "",
                "yes" if row["open_breach"] else "",
            ]
        )

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"sla-report-{timezone.localdate().isoformat()}.xlsx"
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
