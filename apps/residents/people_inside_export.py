"""Hal-hazırda binada olanlar — Excel export (şirkət adına görə qrup)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.reception.models import GuestVisit, VisitStatus
from apps.residents.access import currently_inside_employee_rows

HEADERS = (
    "№",
    "Növ",
    "Ad",
    "Kart",
    "İlk giriş",
    "Hadisə",
)

WIDTHS = [5, 12, 28, 14, 12, 10]
COLS = len(HEADERS)


def _fmt_time(value) -> str:
    if not value:
        return ""
    return timezone.localtime(value).strftime("%H:%M:%S")


def _company_name(row) -> str:
    company = row.get("company")
    if company is None:
        return "—"
    name = (getattr(company, "name", None) or "").strip()
    return name or "—"


def _company_sort_key(name: str) -> tuple:
    return (name == "—", name.casefold())


def _row_sort_key(row) -> tuple:
    kind_order = 0 if row.get("kind") == "employee" else 1
    return (kind_order, (row.get("name") or "").casefold())


def guest_inside_rows(selected_date: date | None = None) -> list[dict]:
    """Reception guests with status INSIDE for the day, sorted by company then name."""
    selected_date = selected_date or timezone.localdate()
    guests = list(
        GuestVisit.objects.filter(scheduled_for=selected_date, status=VisitStatus.INSIDE)
        .select_related("guest", "company")
        .order_by("check_in_at", "guest__full_name")
    )
    rows = [
        {
            "kind": "guest",
            "visit": v,
            "name": v.guest.display_name,
            "company": v.company,
            "card_number": "",
            "in_at": v.check_in_at,
        }
        for v in guests
    ]
    rows.sort(
        key=lambda r: (
            *_company_sort_key(_company_name(r)),
            (r.get("name") or "").casefold(),
        )
    )
    return rows


def people_inside_snapshot(selected_date: date | None = None) -> tuple[list, list, date]:
    selected_date = selected_date or timezone.localdate()
    employees = currently_inside_employee_rows(selected_date)
    guests = guest_inside_rows(selected_date)
    return employees, guests, selected_date


def people_inside_company_count(employee_rows, guest_rows) -> int:
    return len(group_people_inside_by_company(employee_rows, guest_rows))


def group_people_inside_by_company(employee_rows, guest_rows) -> list[tuple[str, list]]:
    buckets: dict[str, list] = defaultdict(list)
    for row in list(employee_rows) + list(guest_rows):
        buckets[_company_name(row)].append(row)
    names = sorted(buckets.keys(), key=_company_sort_key)
    return [(name, sorted(buckets[name], key=_row_sort_key)) for name in names]


def people_inside_xlsx_filename(
    report_date: date | None = None,
    *,
    exported_at: datetime | None = None,
) -> str:
    exported_at = exported_at or timezone.localtime()
    return f"binada-olanlar-{exported_at.strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"


def _box_border(thin, medium, *, left_edge=False, right_edge=False, top_edge=False, bottom_edge=False):
    return Border(
        left=medium if left_edge else thin,
        right=medium if right_edge else thin,
        top=medium if top_edge else thin,
        bottom=medium if bottom_edge else thin,
    )


def build_people_inside_xlsx(
    employee_rows,
    guest_rows,
    *,
    report_date: date | None = None,
    exported_at: datetime | None = None,
) -> bytes:
    report_date = report_date or timezone.localdate()
    exported_at = exported_at or timezone.localtime()
    title_font = Font(name="Calibri", size=14, bold=True, color="0C2745")
    period_font = Font(name="Calibri", size=11, color="475569")
    company_font = Font(name="Calibri", size=12, bold=True, color="0C2745")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    cell_font = Font(name="Calibri", size=11)
    num_font = Font(name="Calibri", size=11, bold=True, color="1F497D")
    left = Alignment(horizontal="left", vertical="center")
    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="94A3B8")
    medium = Side(style="medium", color="1F497D")
    title_fill = PatternFill("solid", fgColor="E8EEF5")
    company_fill = PatternFill("solid", fgColor="D6E3F0")
    header_fill = PatternFill("solid", fgColor="1F497D")
    alt_fill = PatternFill("solid", fgColor="F8FAFC")

    groups = group_people_inside_by_company(employee_rows, guest_rows)
    emp_n = len(employee_rows)
    guest_n = len(guest_rows)
    total = emp_n + guest_n

    wb = Workbook()
    ws = wb.active
    ws.title = "Binada olanlar"

    for i, width in enumerate(WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    stamp = timezone.localtime(exported_at).strftime("%d.%m.%Y %H:%M:%S")

    row = 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=COLS)
    title = ws.cell(row=row, column=1, value=f"Binada olanlar — {stamp}")
    title.font = title_font
    title.alignment = left
    title.fill = title_fill
    for col in range(1, COLS + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = title_fill
        cell.border = _box_border(
            thin, medium, left_edge=col == 1, right_edge=col == COLS, top_edge=True
        )
    row += 1

    subtitle = (
        f"Yüklənmə saatı: {stamp}  ·  {total} nəfər "
        f"({emp_n} əməkdaş · {guest_n} qonaq)  ·  {len(groups)} şirkət"
        f"  ·  gün: {report_date.strftime('%d.%m.%Y')}"
    )
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=COLS)
    sub = ws.cell(row=row, column=1, value=subtitle)
    sub.font = period_font
    sub.alignment = left
    for col in range(1, COLS + 1):
        ws.cell(row=row, column=col).border = _box_border(
            thin, medium, left_edge=col == 1, right_edge=col == COLS, bottom_edge=True
        )
    row += 2

    if not groups:
        ws.cell(row=row, column=1, value="Hal-hazırda binada heç kim yoxdur.").font = period_font
    else:
        for g_i, (company_name, company_rows) in enumerate(groups):
            if g_i > 0:
                row += 1

            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=COLS)
            heading = ws.cell(
                row=row,
                column=1,
                value=f"{company_name}  ({len(company_rows)})",
            )
            heading.font = company_font
            heading.alignment = left
            for col in range(1, COLS + 1):
                cell = ws.cell(row=row, column=col)
                cell.fill = company_fill
                cell.border = _box_border(
                    thin, medium, left_edge=col == 1, right_edge=col == COLS, top_edge=True
                )
            row += 1

            for col, label in enumerate(HEADERS, start=1):
                cell = ws.cell(row=row, column=col, value=label)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = center
                cell.border = _box_border(thin, medium, left_edge=col == 1, right_edge=col == COLS)
            row += 1

            for n, person in enumerate(company_rows, start=1):
                kind_label = "Əməkdaş" if person.get("kind") == "employee" else "Qonaq"
                event_count = person.get("event_count")
                values = [
                    n,
                    kind_label,
                    person.get("name") or "—",
                    person.get("card_number") or "—",
                    _fmt_time(person.get("in_at")) or "—",
                    event_count if person.get("kind") == "employee" else "—",
                ]
                is_last = n == len(company_rows)
                for col, value in enumerate(values, start=1):
                    cell = ws.cell(row=row, column=col, value=value)
                    cell.font = num_font if col == 1 else cell_font
                    cell.alignment = center if col in (1, 2, 4, 5, 6) else left
                    if n % 2 == 0:
                        cell.fill = alt_fill
                    cell.border = _box_border(
                        thin,
                        medium,
                        left_edge=col == 1,
                        right_edge=col == COLS,
                        bottom_edge=is_last,
                    )
                row += 1

    ws.freeze_panes = "A3"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def people_inside_xlsx_http_response(employee_rows, guest_rows, *, report_date: date | None = None) -> HttpResponse:
    report_date = report_date or timezone.localdate()
    exported_at = timezone.localtime()
    payload = build_people_inside_xlsx(
        employee_rows,
        guest_rows,
        report_date=report_date,
        exported_at=exported_at,
    )
    filename = people_inside_xlsx_filename(report_date, exported_at=exported_at)
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response
