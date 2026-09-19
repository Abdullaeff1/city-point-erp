from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import TemplateView, View

from apps.accounts.mixins import SecurityPortalMixin
from apps.residents.access import (
    access_range_bounds,
    build_employee_access_rows,
    employee_attendance_days,
    employee_day_flaps,
    parse_date,
)
from apps.residents.models import (
    AccessLevel,
    RapidCardSwipeAlert,
    ResidentCompany,
    ResidentEmployee,
    ShaftAccessAlert,
)
from apps.tickets.models import OPEN_STATUSES, Ticket


class HomeView(SecurityPortalMixin, TemplateView):
    template_name = "security/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        companies = ResidentCompany.objects.filter(status="active").order_by("-is_internal", "name")
        open_security = Ticket.objects.filter(
            department__code="security",
            status__in=OPEN_STATUSES,
        ).count()
        card_orders = Ticket.objects.filter(
            subcategory__slug="card-order",
            status__in=OPEN_STATUSES,
        ).count()
        open_rapid = RapidCardSwipeAlert.objects.filter(acknowledged_at__isnull=True).count()
        open_shaft = ShaftAccessAlert.objects.filter(acknowledged_at__isnull=True).count()
        ctx.update(
            {
                "company_count": companies.count(),
                "employee_count": ResidentEmployee.objects.filter(is_active=True).count(),
                "open_security_tickets": open_security,
                "open_card_orders": card_orders,
                "open_rapid_alerts": open_rapid,
                "open_shaft_alerts": open_shaft,
                "open_security_alerts": open_rapid + open_shaft,
            }
        )
        return ctx


class AlertListView(SecurityPortalMixin, TemplateView):
    template_name = "security/alerts.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
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
        if alert.acknowledged_at is None:
            alert.acknowledged_at = timezone.now()
            alert.acknowledged_by = request.user
            alert.save(update_fields=["acknowledged_at", "acknowledged_by"])
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

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["alert"] = self.get_alert()
        return ctx


class ShaftAlertAcknowledgeView(SecurityPortalMixin, View):
    def post(self, request, pk):
        alert = get_object_or_404(ShaftAccessAlert, pk=pk)
        if alert.acknowledged_at is None:
            alert.acknowledged_at = timezone.now()
            alert.acknowledged_by = request.user
            alert.save(update_fields=["acknowledged_at", "acknowledged_by"])
            messages.success(request, _("Bildiriş bağlandı."))
        return redirect("security:shaft_alert_detail", pk=alert.pk)


class CompanyListView(SecurityPortalMixin, TemplateView):
    template_name = "security/companies.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        companies = []
        for c in ResidentCompany.objects.all().order_by("-is_internal", "name"):
            companies.append(
                {
                    "company": c,
                    "active_employees": c.employees.filter(is_active=True).count(),
                    "level2": c.employees.filter(is_active=True, access_level=AccessLevel.LEVEL_2).count(),
                }
            )
        ctx["companies"] = companies
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
        employees = company.employees.filter(is_active=True).order_by("full_name")
        rows, inside, left, present = build_employee_access_rows(employees, selected_date)
        ctx.update(
            {
                "company": company,
                "rows": rows,
                "inside": inside,
                "left": left,
                "present": present,
                "today": today,
                "selected_date": selected_date,
                "is_today": selected_date == today,
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
        ctx = super().get_context_data(**kwargs)
        tab = self.request.GET.get("tab", "open")
        qs = Ticket.objects.filter(department__code="security").select_related(
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
        return get_object_or_404(
            Ticket.objects.select_related(
                "company",
                "subcategory",
                "category",
                "related_employee",
                "department",
                "queue",
                "requester",
            ).prefetch_related("attachments"),
            code=self.kwargs["code"],
            department__code="security",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["ticket"] = self.get_ticket()
        return ctx
