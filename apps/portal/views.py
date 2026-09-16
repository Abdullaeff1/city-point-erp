from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import FormView, ListView, TemplateView

from apps.accounts.mixins import ResidentPortalMixin
from apps.comms.models import Announcement, Notification
from apps.documents.models import Document
from apps.erp.forms import PortalTicketForm
from apps.reception.models import GuestVisit
from apps.residents.models import AccessEventType, ResidentEmployee
from apps.tickets.models import OPEN_STATUSES, Ticket, TicketAttachment, TicketStatus
from apps.tickets.services import add_message, apply_sla, next_ticket_code, record_status_event


class HomeView(ResidentPortalMixin, TemplateView):
    template_name = "portal/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.request.user.resident_company
        tickets = Ticket.objects.filter(company=company) if company else Ticket.objects.none()
        spaces = list(company.spaces.select_related("floor", "resident")) if company else []
        latest = tickets.first()
        ctx.update(
            {
                "company": company,
                "spaces": spaces,
                "featured_space": spaces[0] if spaces else None,
                "open_tickets": tickets.filter(status__in=OPEN_STATUSES),
                "recent_tickets": tickets[:6],
                "latest_ticket": latest,
                "announcements": Announcement.objects.all()[:4],
            }
        )
        return ctx


class SpacesView(ResidentPortalMixin, TemplateView):
    template_name = "portal/spaces.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.request.user.resident_company
        ctx["spaces"] = company.spaces.select_related("floor") if company else []
        return ctx


class RequestCreateView(ResidentPortalMixin, FormView):
    template_name = "portal/request_new.html"
    form_class = PortalTicketForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.user.resident_company
        return kwargs

    def form_valid(self, form):
        ticket = form.save(commit=False)
        ticket.code = next_ticket_code()
        ticket.company = self.request.user.resident_company
        ticket.requester = self.request.user
        ticket.status = TicketStatus.SENT
        ticket.save()
        apply_sla(ticket)
        record_status_event(ticket, ticket.status, actor=self.request.user, note="created")
        add_message(ticket, self.request.user, ticket.description, "Siz")
        photo = form.cleaned_data.get("photo")
        if photo:
            TicketAttachment.objects.create(ticket=ticket, file=photo)
        return redirect("portal:request_detail", code=ticket.code)


class RequestListView(ResidentPortalMixin, ListView):
    template_name = "portal/request_list.html"
    context_object_name = "tickets"

    def get_queryset(self):
        company = self.request.user.resident_company
        if not company:
            return Ticket.objects.none()
        qs = Ticket.objects.filter(company=company)
        if self.kwargs.get("scope") == "active":
            qs = qs.filter(status__in=OPEN_STATUSES)
        elif self.kwargs.get("scope") == "history":
            qs = qs.filter(status=TicketStatus.RESOLVED)
        return qs


class RequestDetailView(ResidentPortalMixin, TemplateView):
    template_name = "portal/request_detail.html"

    def get_ticket(self):
        return get_object_or_404(
            Ticket, code=self.kwargs["code"], company=self.request.user.resident_company
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["ticket"] = self.get_ticket()
        return ctx

    def post(self, request, *args, **kwargs):
        ticket = self.get_ticket()
        body = request.POST.get("body", "").strip()
        if body:
            add_message(ticket, request.user, body, "Siz")
        return redirect("portal:request_detail", code=ticket.code)


class AlertsView(ResidentPortalMixin, TemplateView):
    template_name = "portal/alerts.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["notifications"] = Notification.objects.filter(user=user)
        ctx["history"] = Ticket.objects.filter(company=user.resident_company, status=TicketStatus.RESOLVED)
        Notification.objects.filter(user=user, is_read=False).update(is_read=True)
        return ctx


class EmployeeAccessView(ResidentPortalMixin, TemplateView):
    template_name = "portal/employees.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.request.user.resident_company
        today = timezone.localdate()
        employees = ResidentEmployee.objects.filter(company=company, is_active=True)
        rows = []
        inside = 0
        left = 0
        for emp in employees:
            events = list(emp.access_events.filter(occurred_at__date=today).order_by("occurred_at"))
            last_in = next((e for e in reversed(events) if e.event_type == AccessEventType.IN), None)
            last_out = next((e for e in reversed(events) if e.event_type == AccessEventType.OUT), None)
            status = "Çıxış" if last_out and (not last_in or last_out.occurred_at >= last_in.occurred_at) else "İçəridə"
            if events:
                if status == "İçəridə":
                    inside += 1
                else:
                    left += 1
            rows.append(
                {
                    "employee": emp,
                    "in_at": last_in.occurred_at if last_in else None,
                    "out_at": last_out.occurred_at if last_out else None,
                    "status": status if events else "—",
                }
            )
        ctx.update({"rows": rows, "inside": inside, "left": left, "today": today})
        return ctx


class GuestsView(ResidentPortalMixin, FormView):
    template_name = "portal/guests.html"
    form_class = None  # set in get_form_class

    def get_form_class(self):
        from apps.erp.forms import PortalGuestForm

        return PortalGuestForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.user.resident_company
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.request.user.resident_company
        ctx["visits"] = (
            GuestVisit.objects.filter(company=company, scheduled_for=timezone.localdate())
            .select_related("guest", "host", "floor", "space", "visit_type")
            if company
            else GuestVisit.objects.none()
        )
        return ctx

    def form_valid(self, form):
        from apps.reception.services import pre_register_visit

        company = self.request.user.resident_company
        visit = pre_register_visit(
            company=company,
            first_name=form.cleaned_data["first_name"],
            last_name=form.cleaned_data["last_name"],
            email=form.cleaned_data.get("email") or "",
            phone=form.cleaned_data.get("phone") or "",
            host=form.cleaned_data.get("host"),
            space=form.cleaned_data.get("space"),
            location_note=form.cleaned_data.get("location_note") or "",
            visit_type=form.cleaned_data.get("visit_type"),
            portal_user=self.request.user,
        )
        if form.cleaned_data.get("expected_arrival"):
            visit.expected_arrival = form.cleaned_data["expected_arrival"]
            visit.scheduled_for = form.cleaned_data["expected_arrival"].date()
            visit.save(update_fields=["expected_arrival", "scheduled_for", "updated_at"])
        return redirect("portal:guests")


class AnnouncementsView(ResidentPortalMixin, ListView):
    template_name = "portal/announcements.html"
    queryset = Announcement.objects.all()
    context_object_name = "announcements"


class DocumentsView(ResidentPortalMixin, ListView):
    template_name = "portal/documents.html"
    context_object_name = "documents"

    def get_queryset(self):
        company = self.request.user.resident_company
        return Document.objects.filter(Q(company=company) | Q(company__isnull=True))
