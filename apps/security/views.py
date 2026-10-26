from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import TemplateView, View

from apps.accounts.mixins import SecurityPortalMixin
from apps.comms.models import Notification
from apps.core.search import filter_text_search
from apps.reception.models import GuestVisit, VisitStatus
from apps.residents.access import (
    access_range_bounds,
    build_employee_access_rows,
    currently_inside_employee_rows,
    employee_attendance_days,
    employee_day_flaps,
    parse_date,
)
from apps.residents.access_export import access_xlsx_http_response
from apps.residents.models import (
    AccessEvent,
    AccessEventType,
    AccessResult,
    AccessLevel,
    RapidCardSwipeAlert,
    ResidentCompany,
    ResidentEmployee,
    ShaftAccessAlert,
)
from apps.tickets.access import tickets_visible_to
from apps.tickets.models import OPEN_STATUSES, Ticket, TicketStatus

RECENT_EVENTS_LIMIT = 80


def _serialize_access_event(event: AccessEvent) -> dict:
    local = timezone.localtime(event.occurred_at)
    name = event.employee_name or (event.employee.full_name if event.employee_id else "—")
    company = ""
    if event.employee_id and event.employee.company_id:
        company = event.employee.company.name
    badge = (event.employee.card_number if event.employee_id else "") or ""
    card = badge.strip() or (event.card_number or "").strip()
    return {
        "id": event.pk,
        "occurred_at": local.strftime("%d.%m.%Y %H:%M:%S"),
        "time": local.strftime("%H:%M:%S"),
        "date": local.strftime("%d.%m.%Y"),
        "employee": name,
        "employee_id": event.employee_id,
        "company": company,
        "card_number": card,
        "reader": event.reader_name or "—",
        "event_type": event.event_type,
        "event_label": str(
            _("Giriş") if event.event_type == AccessEventType.IN else _("Çıxış")
        ),
        "is_in": event.event_type == AccessEventType.IN,
        "granted": event.result != AccessResult.DENIED,
        "result_label": str(
            _("Uğurlu") if event.result != AccessResult.DENIED else _("Uğursuz")
        ),
    }


def recent_access_events(limit: int = RECENT_EVENTS_LIMIT):
    return (
        AccessEvent.objects.select_related("employee", "employee__company")
        .order_by("-occurred_at", "-id")[:limit]
    )


def _guest_visits_for_date(*, company=None, selected_date=None):
    selected_date = selected_date or timezone.localdate()
    qs = (
        GuestVisit.objects.filter(scheduled_for=selected_date)
        .exclude(status__in=(VisitStatus.CANCELLED, VisitStatus.NO_SHOW))
        .select_related("guest", "company", "host", "visit_type", "visitor_access")
        .order_by("-check_in_at", "-id")
    )
    if company is not None:
        qs = qs.filter(company=company)
    return qs


def _guest_stats(visits):
    inside = sum(1 for v in visits if v.status == VisitStatus.INSIDE)
    left = sum(1 for v in visits if v.status in (VisitStatus.LEFT, VisitStatus.RETURN_PENDING))
    return {"guest_inside": inside, "guest_left": left, "guest_total": len(visits)}


def _mark_user_notifications_read(user) -> None:
    Notification.objects.filter(user=user, is_read=False).update(is_read=True)


def _auto_acknowledge(alert, user) -> None:
    """Opening an alert detail marks it read/closed for the badge."""
    if alert.acknowledged_at is None:
        alert.acknowledged_at = timezone.now()
        alert.acknowledged_by = user
        alert.save(update_fields=["acknowledged_at", "acknowledged_by"])
    _mark_user_notifications_read(user)


class HomeView(SecurityPortalMixin, TemplateView):
    template_name = "security/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        companies = ResidentCompany.objects.filter(status="active").order_by("-is_internal", "name")
        visible = tickets_visible_to(self.request.user)
        open_security = visible.filter(status__in=OPEN_STATUSES).count()
        card_orders = visible.filter(
            subcategory__slug="card-order",
            status__in=OPEN_STATUSES,
        ).count()
        open_rapid = RapidCardSwipeAlert.objects.filter(acknowledged_at__isnull=True).count()
        open_shaft = ShaftAccessAlert.objects.filter(acknowledged_at__isnull=True).count()
        today = timezone.localdate()
        guest_inside = GuestVisit.objects.filter(
            status=VisitStatus.INSIDE, scheduled_for=today
        ).count()
        employees_inside = currently_inside_employee_rows(today)
        events = list(recent_access_events())
        ctx.update(
            {
                "company_count": companies.count(),
                "employee_count": ResidentEmployee.objects.filter(is_active=True).count(),
                "open_security_tickets": open_security,
                "open_card_orders": card_orders,
                "open_rapid_alerts": open_rapid,
                "open_shaft_alerts": open_shaft,
                "open_security_alerts": open_rapid + open_shaft,
                "guest_inside_today": guest_inside,
                "people_inside_count": len(employees_inside) + guest_inside,
                "recent_events": events,
                "recent_events_json": [_serialize_access_event(e) for e in events],
            }
        )
        return ctx


class EventsFeedView(SecurityPortalMixin, View):
    """JSON feed — AxTraxNG Events üslubunda canlı siyahı."""

    def get(self, request):
        events = recent_access_events()
        return JsonResponse(
            {
                "ok": True,
                "generated_at": timezone.localtime().strftime("%H:%M:%S"),
                "results": [_serialize_access_event(e) for e in events],
            }
        )


class PeopleInsideView(SecurityPortalMixin, TemplateView):
    """Hal-hazırda binada olan əməkdaşlar + qonaqlar (bu gün)."""

    template_name = "security/people_inside.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        employees = currently_inside_employee_rows(today)
        guests = list(
            GuestVisit.objects.filter(scheduled_for=today, status=VisitStatus.INSIDE)
            .select_related("guest", "company")
            .order_by("check_in_at", "guest__full_name")
        )
        guest_rows = [
            {
                "kind": "guest",
                "visit": v,
                "name": v.guest.display_name,
                "company": v.company,
                "in_at": v.check_in_at,
            }
            for v in guests
        ]
        ctx.update(
            {
                "today": today,
                "employee_rows": employees,
                "guest_rows": guest_rows,
                "inside_total": len(employees) + len(guest_rows),
            }
        )
        return ctx


class EmployeeListView(SecurityPortalMixin, TemplateView):
    """Bütün aktiv əməkdaşlar — server axtarışı + səhifələmə."""

    template_name = "security/employees.html"
    page_size = 100

    def get_context_data(self, **kwargs):
        from django.core.paginator import Paginator

        ctx = super().get_context_data(**kwargs)
        # Trailing space saxlanılır — live axtarışda Space basanda kursor geriyə düşməsin
        q = self.request.GET.get("q") or ""
        q_filter = q.strip()
        qs = (
            ResidentEmployee.objects.filter(is_active=True)
            .select_related("company")
            .order_by("full_name", "id")
        )
        if q_filter:
            qs = filter_text_search(
                qs, q_filter, "full_name", "card_number", "company__name"
            )
        total = qs.count()
        paginator = Paginator(qs, self.page_size)
        try:
            page_num = max(1, int(self.request.GET.get("page") or 1))
        except (TypeError, ValueError):
            page_num = 1
        page = paginator.get_page(page_num)
        ctx.update(
            {
                "employees": page.object_list,
                "page_obj": page,
                "paginator": paginator,
                "employee_count": total,
                "employee_total_active": ResidentEmployee.objects.filter(is_active=True).count()
                if q_filter
                else total,
                "q": q,
                "today": timezone.localdate(),
            }
        )
        return ctx


class AlertListView(SecurityPortalMixin, TemplateView):
    template_name = "security/alerts.html"

    def get(self, request, *args, **kwargs):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from apps.comms.links import user_notifications

        ctx = super().get_context_data(**kwargs)
        ctx["notifications"] = user_notifications(self.request.user, namespace="security")
        kind = self.kwargs.get("kind") or self.request.GET.get("kind") or "rapid"
        if kind not in {"rapid", "shaft"}:
            kind = "rapid"
        tab = self.request.GET.get("tab", "open")
        if kind == "shaft":
            qs = ShaftAccessAlert.objects.select_related("employee", "employee__company")
            if tab == "open":
                qs = qs.filter(acknowledged_at__isnull=True)
            elif tab == "acked":
                qs = qs.filter(acknowledged_at__isnull=False)
            ctx.update({"shaft_alerts": qs[:200], "alerts": [], "kind": kind, "tab": tab})
        else:
            qs = RapidCardSwipeAlert.objects.select_related("employee", "employee__company")
            if tab == "open":
                qs = qs.filter(acknowledged_at__isnull=True)
            elif tab == "acked":
                qs = qs.filter(acknowledged_at__isnull=False)
            ctx.update({"alerts": qs[:200], "shaft_alerts": [], "kind": kind, "tab": tab})
        return ctx


class AlertDetailView(SecurityPortalMixin, TemplateView):
    template_name = "security/alert_detail.html"

    def get_alert(self):
        return get_object_or_404(
            RapidCardSwipeAlert.objects.select_related(
                "employee", "employee__company", "acknowledged_by"
            ),
            pk=self.kwargs["pk"],
        )

    def get(self, request, *args, **kwargs):
        alert = self.get_alert()
        _auto_acknowledge(alert, request.user)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        alert = self.get_alert()
        from django.utils.dateparse import parse_datetime
        from django.utils.formats import date_format

        swipes = []
        for row in alert.swipes or []:
            at_raw = row.get("at")
            at_dt = parse_datetime(str(at_raw)) if at_raw else None
            if at_dt and timezone.is_naive(at_dt):
                at_dt = timezone.make_aware(at_dt, timezone.get_current_timezone())
            swipes.append(
                {
                    "at_display": date_format(at_dt, "d.m.Y H:i:s") if at_dt else (at_raw or "—"),
                    "event_type": row.get("event_type"),
                    "access_event_id": row.get("access_event_id"),
                    "reader_name": (row.get("reader_name") or "").strip(),
                    "reader_id": row.get("reader_id"),
                }
            )
        ctx.update({"alert": alert, "swipes": swipes})
        return ctx


class AlertAcknowledgeView(SecurityPortalMixin, View):
    def post(self, request, pk):
        alert = get_object_or_404(RapidCardSwipeAlert, pk=pk)
        _auto_acknowledge(alert, request.user)
        messages.success(request, _("Bildiriş bağlandı."))
        return redirect("security:alert_detail", pk=alert.pk)


class ShaftAlertDetailView(SecurityPortalMixin, TemplateView):
    template_name = "security/shaft_alert_detail.html"

    def get_alert(self):
        return get_object_or_404(
            ShaftAccessAlert.objects.select_related(
                "employee", "employee__company", "acknowledged_by", "access_event"
            ),
            pk=self.kwargs["pk"],
        )

    def get(self, request, *args, **kwargs):
        alert = self.get_alert()
        _auto_acknowledge(alert, request.user)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["alert"] = self.get_alert()
        return ctx


class ShaftAlertAcknowledgeView(SecurityPortalMixin, View):
    def post(self, request, pk):
        alert = get_object_or_404(ShaftAccessAlert, pk=pk)
        _auto_acknowledge(alert, request.user)
        messages.success(request, _("Bildiriş bağlandı."))
        return redirect("security:shaft_alert_detail", pk=alert.pk)


class CompanyListView(SecurityPortalMixin, TemplateView):
    template_name = "security/companies.html"

    def get_context_data(self, **kwargs):
        from django.db.models import Count

        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        q = (self.request.GET.get("q") or "").strip()
        employee_hits = []
        matched_company_ids: set[int] | None = None
        if q:
            employee_hits = list(
                filter_text_search(
                    ResidentEmployee.objects.filter(is_active=True),
                    q,
                    "full_name",
                    "card_number",
                )
                .select_related("company")
                .order_by("full_name")[:80]
            )
            matched_company_ids = {e.company_id for e in employee_hits}
            matched_company_ids |= set(
                filter_text_search(
                    ResidentCompany.objects.all(), q, "name"
                ).values_list("id", flat=True)
            )

        guest_inside_by_company = {
            row["company_id"]: row["c"]
            for row in GuestVisit.objects.filter(
                status=VisitStatus.INSIDE, scheduled_for=today
            )
            .values("company_id")
            .annotate(c=Count("id"))
        }

        company_qs = (
            ResidentCompany.objects.all()
            .annotate(
                active_employees=Count(
                    "employees",
                    filter=Q(employees__is_active=True),
                    distinct=True,
                ),
                level2=Count(
                    "employees",
                    filter=Q(employees__is_active=True, employees__access_level=AccessLevel.LEVEL_2),
                    distinct=True,
                ),
            )
            .order_by("-is_internal", "name")
        )
        if matched_company_ids is not None:
            company_qs = (
                company_qs.filter(id__in=matched_company_ids) if matched_company_ids else company_qs.none()
            )

        companies = [
            {
                "company": c,
                "active_employees": c.active_employees,
                "level2": c.level2,
                "guests_inside": guest_inside_by_company.get(c.id, 0),
            }
            for c in company_qs
        ]
        ctx.update(
            {
                "companies": companies,
                "q": q,
                "employee_hits": employee_hits,
                "employee_hit_count": len(employee_hits),
            }
        )
        return ctx


class CompanyEmployeesView(SecurityPortalMixin, TemplateView):
    template_name = "security/company_employees.html"

    def get_company(self):
        return get_object_or_404(ResidentCompany, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        today = timezone.localdate()
        selected_date = parse_date(self.request.GET.get("date"), today)
        tab = self.request.GET.get("tab") or "employees"
        if tab not in {"employees", "guests"}:
            tab = "employees"
        employees = company.employees.filter(is_active=True).order_by("full_name")
        rows, inside, left, present = build_employee_access_rows(employees, selected_date)
        guest_visits = list(_guest_visits_for_date(company=company, selected_date=selected_date))
        guest_stats = _guest_stats(guest_visits)
        export_preset, export_from, export_to = access_range_bounds(
            self.request, default_preset="month"
        )
        if "range" not in self.request.GET:
            export_preset = "month"
            export_from = today.replace(day=1)
            export_to = today
        ctx.update(
            {
                "company": company,
                "rows": rows,
                "inside": inside,
                "left": left,
                "present": present,
                "guest_visits": guest_visits,
                "tab": tab,
                "today": today,
                "selected_date": selected_date,
                "is_today": selected_date == today,
                "export_preset": export_preset,
                "export_from": export_from,
                "export_to": export_to,
                **guest_stats,
            }
        )
        return ctx


class CompanyAccessExportView(SecurityPortalMixin, View):
    """Security: Excel attendance for any company (including City Point internal)."""

    def get(self, request, pk, employee_pk=None):
        company = get_object_or_404(ResidentCompany, pk=pk)
        _preset, date_from, date_to = access_range_bounds(request, default_preset="month")
        employee = None
        if employee_pk is not None:
            employee = get_object_or_404(ResidentEmployee, pk=employee_pk, company=company)
        roster = (request.GET.get("roster") or "active").strip().lower()
        return access_xlsx_http_response(
            company,
            date_from,
            date_to,
            employee=employee,
            roster=roster,
        )


class GuestsView(SecurityPortalMixin, TemplateView):
    """Building-wide guest check-in / check-out journal for security."""

    template_name = "security/guests.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        selected_date = parse_date(self.request.GET.get("date"), today)
        company_id = self.request.GET.get("company") or ""
        company = None
        if company_id.isdigit():
            company = ResidentCompany.objects.filter(pk=int(company_id)).first()
        visits = list(_guest_visits_for_date(company=company, selected_date=selected_date))
        stats = _guest_stats(visits)
        ctx.update(
            {
                "visits": visits,
                "companies": ResidentCompany.objects.filter(status="active").order_by("name"),
                "filter_company": company,
                "today": today,
                "selected_date": selected_date,
                "is_today": selected_date == today,
                **stats,
            }
        )
        return ctx


class EmployeeAccessDetailView(SecurityPortalMixin, TemplateView):
    template_name = "security/employee_access_detail.html"

    def get_employee(self):
        return get_object_or_404(
            ResidentEmployee.objects.select_related("company"),
            pk=self.kwargs["pk"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        employee = self.get_employee()
        preset, date_from, date_to = access_range_bounds(self.request, default_preset="today")
        single_day = date_from == date_to
        if single_day:
            flaps = employee_day_flaps(employee, date_from)
            days = []
            in_count = sum(1 for e in flaps if e.event_type == "in")
            out_count = len(flaps) - in_count
        else:
            flaps = []
            days = employee_attendance_days(employee, date_from, date_to)
            in_count = out_count = 0
        ctx.update(
            {
                "employee": employee,
                "company": employee.company,
                "days": days,
                "flaps": flaps,
                "single_day": single_day,
                "preset": preset,
                "date_from": date_from,
                "date_to": date_to,
                "in_count": in_count,
                "out_count": out_count,
                "present_days": len(days) if not single_day else (1 if flaps else 0),
                "today": timezone.localdate(),
            }
        )
        return ctx


class TicketListView(SecurityPortalMixin, TemplateView):
    template_name = "security/tickets.html"

    def get_context_data(self, **kwargs):
        from apps.tickets.access import tickets_visible_to

        ctx = super().get_context_data(**kwargs)
        tab = self.request.GET.get("tab", "open")
        qs = tickets_visible_to(self.request.user).select_related(
            "company", "subcategory", "related_employee", "queue", "assignee"
        )
        if tab == "card-orders":
            qs = qs.filter(subcategory__slug="card-order")
        elif tab == "open":
            qs = qs.filter(status__in=OPEN_STATUSES)
        ctx.update({"tickets": qs[:200], "tab": tab})
        return ctx


class TicketDetailView(SecurityPortalMixin, TemplateView):
    template_name = "security/ticket_detail.html"

    def get_ticket(self):
        from apps.tickets.access import tickets_visible_to

        return get_object_or_404(
            tickets_visible_to(self.request.user)
            .select_related(
                "company",
                "subcategory",
                "category",
                "related_employee",
                "department",
                "queue",
                "requester",
                "assignee",
            )
            .prefetch_related("attachments"),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        from apps.tickets.access import can_mutate_ticket, department_assignees

        ctx = super().get_context_data(**kwargs)
        ticket = self.get_ticket()
        ctx["ticket"] = ticket
        ctx["can_mutate"] = can_mutate_ticket(self.request.user, ticket)
        ctx["staff_users"] = department_assignees(ticket)
        ctx["status_events"] = ticket.status_events.select_related("actor")[:40]
        return ctx

    def post(self, request, *args, **kwargs):
        from django.contrib import messages

        from apps.core.services import DomainError
        from apps.tickets.services import (
            advance_ticket_status,
            assign_ticket,
            set_ticket_status,
        )

        ticket = self.get_ticket()
        action = request.POST.get("action")
        try:
            if action == "advance" and ticket.next_status:
                advance_ticket_status(ticket, actor=request.user)
            elif action == "waiting":
                reason = request.POST.get("waiting_reason", "").strip()
                set_ticket_status(
                    ticket,
                    TicketStatus.WAITING,
                    actor=request.user,
                    note=reason,
                    waiting_reason=reason,
                )
            elif action == "close":
                set_ticket_status(ticket, TicketStatus.CLOSED, actor=request.user)
            elif action == "reopen":
                set_ticket_status(
                    ticket, TicketStatus.REOPENED, actor=request.user, note="reopened"
                )
            elif action == "assign":
                assign_ticket(
                    ticket,
                    actor=request.user,
                    assignee_id=request.POST.get("assignee") or None,
                )
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect("security:ticket_detail", code=ticket.code)
