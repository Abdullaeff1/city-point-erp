from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import FormView, ListView, TemplateView, View

from apps.accounts.mixins import RoleRequiredMixin, StaffRequiredMixin
from apps.accounts.models import Role, User
from apps.documents.models import Document
from apps.erp.forms import GuestVisitForm
from apps.property.models import Floor, Space
from apps.reception.models import Guest, GuestVisit, VisitStatus
from apps.residents.models import ResidentCompany
from apps.tickets.models import OPEN_STATUSES, Ticket, TicketStatus
from apps.tickets.services import add_message, advance_ticket_status


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "erp/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        open_qs = Ticket.objects.filter(status__in=OPEN_STATUSES).select_related("category", "company", "space")
        open_list = list(open_qs)
        sla_tickets = [t for t in open_list if t.sla_risk]
        breached = [t for t in open_list if t.sla_breached]
        sla_ticket = breached[0] if breached else (sla_tickets[0] if sla_tickets else None)
        today_visits = GuestVisit.objects.filter(scheduled_for=today).select_related("guest", "company")
        recent_tickets = Ticket.objects.select_related("category", "company")[:6]
        activities = []
        for t in Ticket.objects.order_by("-updated_at")[:5]:
            activities.append({"at": t.updated_at, "text": f"{t.code} yeniləndi · {t.get_status_display()}"})
        for v in today_visits.filter(check_in_at__isnull=False).order_by("-check_in_at")[:4]:
            activities.append({"at": v.check_in_at, "text": f"Qonaq giriş etdi · {v.guest.full_name}"})
        activities.sort(key=lambda x: x["at"] or timezone.now(), reverse=True)
        ctx.update(
            {
                "guest_count": today_visits.count(),
                "open_count": len(open_list),
                "sla_risk_count": len(sla_tickets),
                "sla_breach_count": len(breached),
                "sla_ticket": sla_ticket,
                "new_residents": ResidentCompany.objects.filter(status="active").count(),
                "waiting_guests": today_visits.filter(status=VisitStatus.WAITING),
                "today_visits": today_visits[:8],
                "recent_open": open_list[:6],
                "activities": activities[:8],
                "unassigned": Ticket.objects.filter(status=TicketStatus.SENT, assignee__isnull=True)[:5],
            }
        )
        return ctx


class ReceptionView(RoleRequiredMixin, FormView):
    template_name = "erp/reception.html"
    form_class = GuestVisitForm
    allowed_roles = (Role.RECEPTION,)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        ctx["visits"] = GuestVisit.objects.filter(scheduled_for=today).select_related(
            "guest", "company", "host", "floor", "space"
        )
        return ctx

    def form_valid(self, form):
        guest, _ = Guest.objects.get_or_create(full_name=form.cleaned_data["full_name"])
        GuestVisit.objects.create(
            guest=guest,
            company=form.cleaned_data["company"],
            host=form.cleaned_data.get("host"),
            floor=form.cleaned_data.get("floor"),
            space=form.cleaned_data.get("space"),
            location_note=form.cleaned_data.get("location_note") or "",
            status=VisitStatus.WAITING,
            scheduled_for=timezone.localdate(),
        )
        messages.success(self.request, "Qonaq qeydə alındı.")
        return redirect("erp:reception")


class ReceptionStatusView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def post(self, request, pk):
        visit = get_object_or_404(GuestVisit, pk=pk)
        action = request.POST.get("action")
        now = timezone.now()
        if action == "checkin":
            visit.status = VisitStatus.INSIDE
            visit.check_in_at = now
        elif action == "checkout":
            visit.status = VisitStatus.LEFT
            visit.check_out_at = now
        visit.save()
        return redirect("erp:reception")


class TicketListView(RoleRequiredMixin, ListView):
    template_name = "erp/tickets.html"
    context_object_name = "tickets"
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM)

    def get_queryset(self):
        qs = Ticket.objects.select_related("category", "company", "space", "assignee")
        tab = self.request.GET.get("tab", "all")
        if tab == "open":
            qs = qs.filter(status__in=OPEN_STATUSES)
        elif tab == "sla":
            ids = [t.id for t in qs.filter(status__in=OPEN_STATUSES) if t.sla_risk]
            qs = qs.filter(id__in=ids)
        elif tab == "mine":
            qs = qs.filter(assignee=self.request.user)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["tab"] = self.request.GET.get("tab", "all")
        return ctx


class TicketDetailView(RoleRequiredMixin, TemplateView):
    template_name = "erp/ticket_detail.html"
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM)

    def get_ticket(self):
        return get_object_or_404(Ticket, code=self.kwargs["code"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["ticket"] = self.get_ticket()
        ctx["staff_users"] = User.objects.filter(role__in=[Role.SERVICE_DESK, Role.PROPERTY_FM, Role.ADMIN])
        ctx["status_events"] = self.get_ticket().status_events.select_related("actor")
        return ctx

    def post(self, request, *args, **kwargs):
        ticket = self.get_ticket()
        action = request.POST.get("action")
        if action == "advance" and ticket.next_status:
            advance_ticket_status(ticket, actor=request.user)
        elif action == "assign":
            assignee_id = request.POST.get("assignee")
            ticket.assignee_id = assignee_id or None
            ticket.save(update_fields=["assignee", "updated_at"])
        elif action == "message":
            body = request.POST.get("body", "").strip()
            if body:
                add_message(ticket, request.user, body, "CityPoint")
        return redirect("erp:ticket_detail", code=ticket.code)


class SpaceListView(RoleRequiredMixin, ListView):
    template_name = "erp/spaces.html"
    queryset = Space.objects.select_related("floor", "resident")
    context_object_name = "spaces"
    allowed_roles = (Role.PROPERTY_FM,)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        floors = Floor.objects.prefetch_related("spaces__resident").order_by("code")
        floor_rows = []
        for floor in floors:
            spaces = list(floor.spaces.all())
            total = len(spaces)
            occupied = sum(1 for s in spaces if s.resident_id)
            pct = int(occupied / total * 100) if total else 0
            floor_rows.append({"floor": floor, "total": total, "occupied": occupied, "pct": pct, "spaces": spaces})
        ctx.update(
            {
                "floor_count": floors.count(),
                "space_count": Space.objects.count(),
                "active_residents": ResidentCompany.objects.filter(status="active").count(),
                "guest_today": GuestVisit.objects.filter(scheduled_for=timezone.localdate()).count(),
                "floor_rows": floor_rows,
            }
        )
        return ctx


class SpaceDetailView(RoleRequiredMixin, TemplateView):
    template_name = "erp/space_detail.html"
    allowed_roles = (Role.PROPERTY_FM,)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        space = get_object_or_404(Space.objects.select_related("floor", "resident"), code=self.kwargs["code"])
        tab = self.request.GET.get("tab", "overview")
        ctx["space"] = space
        ctx["tab"] = tab
        ctx["open_tickets"] = space.tickets.filter(status__in=OPEN_STATUSES)
        ctx["ticket_history"] = space.tickets.filter(status=TicketStatus.RESOLVED)
        ctx["all_tickets"] = space.tickets.select_related("category")[:20]
        ctx["assets"] = space.assets.all()
        ctx["documents"] = space.documents.all()
        ctx["employees"] = (
            space.resident.employees.filter(is_active=True) if space.resident_id else []
        )
        return ctx


class ResidentListView(StaffRequiredMixin, ListView):
    template_name = "erp/residents.html"
    queryset = ResidentCompany.objects.all()
    context_object_name = "companies"


class ResidentDetailView(StaffRequiredMixin, TemplateView):
    template_name = "erp/resident_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = get_object_or_404(ResidentCompany, slug=self.kwargs["slug"])
        today = timezone.localdate()
        ctx.update(
            {
                "company": company,
                "spaces": company.spaces.select_related("floor"),
                "open_tickets": company.tickets.filter(status__in=OPEN_STATUSES),
                "employees": company.employees.filter(is_active=True),
                "guest_today": company.guest_visits.filter(scheduled_for=today).count(),
                "latest_ticket": company.tickets.first(),
            }
        )
        return ctx


class DocumentsView(StaffRequiredMixin, ListView):
    template_name = "erp/documents.html"
    queryset = Document.objects.select_related("company", "space")
    context_object_name = "documents"


class ReportsView(RoleRequiredMixin, TemplateView):
    template_name = "erp/reports.html"
    allowed_roles = (Role.MANAGEMENT, Role.ADMIN)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        open_tickets = list(Ticket.objects.filter(status__in=OPEN_STATUSES))
        ctx.update(
            {
                "open_count": len(open_tickets),
                "sla_risk_count": sum(1 for t in open_tickets if t.sla_risk),
                "guest_count": GuestVisit.objects.filter(scheduled_for=timezone.localdate()).count(),
                "companies": ResidentCompany.objects.filter(status="active"),
            }
        )
        return ctx
