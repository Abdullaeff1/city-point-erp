"""Excel exports for finance portal."""

from __future__ import annotations

from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone


def _workbook_response(wb, filename: str) -> HttpResponse:
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def aging_xlsx_response(buckets: dict) -> HttpResponse:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "AR Aging"
    ws.append(["Bucket", "Invoice", "Party", "Due", "Balance", "Days"])
    labels = {
        "current": "Current",
        "1_30": "1-30",
        "31_60": "31-60",
        "61_90": "61-90",
        "90_plus": "90+",
    }
    for key, rows in buckets.items():
        for row in rows:
            inv = row["invoice"]
            ws.append(
                [
                    labels.get(key, key),
                    inv.code,
                    inv.party.display_name if inv.party_id else "",
                    inv.due_date.isoformat() if inv.due_date else "",
                    float(row["balance"]),
                    row["days_overdue"],
                ]
            )
    return _workbook_response(wb, f"ar-aging-{timezone.localdate().isoformat()}.xlsx")


def trial_balance_xlsx_response(rows: list[dict]) -> HttpResponse:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Trial balance"
    ws.append(["Code", "Name", "Type", "Debit", "Credit", "Balance"])
    for row in rows:
        ws.append(
            [
                row["code"],
                row["name"],
                row["account_type"],
                float(row["debit"]),
                float(row["credit"]),
                float(row["balance"]),
            ]
        )
    return _workbook_response(wb, f"trial-balance-{timezone.localdate().isoformat()}.xlsx")


def invoices_xlsx_response(invoices) -> HttpResponse:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Invoices"
    ws.append(["Code", "Party", "Status", "Issue", "Due", "Total", "Currency"])
    for inv in invoices:
        ws.append(
            [
                inv.code,
                inv.party.display_name if inv.party_id else "",
                inv.status,
                inv.issue_date.isoformat() if inv.issue_date else "",
                inv.due_date.isoformat() if inv.due_date else "",
                float(inv.total or 0),
                inv.currency,
            ]
        )
    return _workbook_response(wb, f"invoices-{timezone.localdate().isoformat()}.xlsx")
