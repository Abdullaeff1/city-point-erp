from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import FormView, ListView, TemplateView, View
import json
import csv
from io import StringIO

from apps.accounts.mixins import RoleRequiredMixin, StaffRequiredMixin
from apps.accounts.models import Role, User
from apps.core.services import DomainError
from apps.documents.models import Document
from apps.erp.forms import GuestVisitForm
from apps.parties.models import Party
from apps.property.models import Floor, Space
from apps.reception.models import GuestVisit, VisitStatus, mask_fin
from apps.reception.services import (
    ReceptionService,
    filter_visits,
    today_visits_queryset,
)
from apps.residents.access import (
    access_range_bounds,
    build_employee_access_rows,
    employee_attendance_days,
    employee_day_flaps,
    employee_roster_qs,
    parse_date,
)
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.rbac.services import user_has_permission
from apps.tickets.models import CLOSED_STATUSES, OPEN_STATUSES, Ticket, TicketPriority, TicketStatus
from apps.tickets.services import (
    add_message,
    advance_ticket_status,
    apply_sla,
    create_crm_opportunity_from_ticket,
    set_ticket_status,
)


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
            activities.append({"at": v.check_in_at, "text": f"Qonaq giriş etdi · {v.guest.display_name}"})
        activities.sort(key=lambda x: x["at"] or timezone.now(), reverse=True)
        ctx.update(
            {
                "guest_count": today_visits.count(),
                "open_count": len(open_list),
                "sla_risk_count": len(sla_tickets),
                "sla_breach_count": len(breached),
                "sla_ticket": sla_ticket,
                "new_residents": ResidentCompany.objects.filter(status="active", is_internal=False).count(),
                "waiting_guests": today_visits.filter(
                    status__in=[VisitStatus.WAITING, VisitStatus.PRE_REGISTERED]
                ),
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

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not (
            user_has_permission(request.user, "reception.view")
            or user_has_permission(request.user, "reception.manage")
        ):
            raise PermissionDenied("Reception baxış icazəsi yoxdur.")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        company_id = self.request.GET.get("company") or self.request.POST.get("company")
        if company_id:
            kwargs["company"] = ResidentCompany.objects.filter(pk=company_id).first()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "")
        company_id = self.request.GET.get("company") or ""
        id_not_returned = self.request.GET.get("id_not_returned") == "1"
        base = today_visits_queryset(today)
        visits = filter_visits(
            base,
            q=q,
            status=status,
            company_id=company_id or None,
            id_not_returned=id_not_returned,
        )
        inside = GuestVisit.objects.filter(status=VisitStatus.INSIDE).select_related(
            "guest", "company", "host", "visit_type", "visitor_access"
        )
        can_sensitive = user_has_permission(self.request.user, "reception.view_sensitive_data")
        can_override = user_has_permission(self.request.user, "reception.override_id")
        can_export = user_has_permission(self.request.user, "reception.export")
        stats = {
            "inside": GuestVisit.objects.filter(status=VisitStatus.INSIDE).count(),
            "today": base.count(),
            "waiting": base.filter(
                status__in=[VisitStatus.WAITING, VisitStatus.PRE_REGISTERED]
            ).count(),
            "checked_out": base.filter(status=VisitStatus.LEFT).count(),
            "no_show": base.filter(status=VisitStatus.NO_SHOW).count(),
            "id_pending": GuestVisit.objects.filter(
                status=VisitStatus.RETURN_PENDING
            ).count()
            + GuestVisit.objects.filter(
                id_document_held=True, status=VisitStatus.INSIDE
            ).count(),
        }
        ctx.update(
            {
                "visits": visits,
                "inside_visits": inside[:50],
                "stats": stats,
                "q": q,
                "filter_status": status,
                "filter_company": company_id,
                "id_not_returned": id_not_returned,
                "companies": ResidentCompany.objects.filter(status="active", is_internal=False),
                "hosts_json": json.dumps(
                    list(
                        ResidentEmployee.objects.filter(is_active=True).values(
                            "id", "full_name", "company_id"
                        )
                    )
                ),
                "can_sensitive": can_sensitive,
                "can_override": can_override,
                "can_export": can_export,
                "mask_fin": mask_fin,
            }
        )
        return ctx

    def form_valid(self, form):
        if not user_has_permission(self.request.user, "reception.create_visit"):
            raise PermissionDenied("Qonaq yaratmaq icazəsi yoxdur.")
        try:
            ReceptionService.register_walk_in(
                fin_code=form.cleaned_data["fin_code"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                phone=form.cleaned_data.get("phone") or "",
                company=form.cleaned_data["company"],
                host=form.cleaned_data.get("host"),
                id_document_held=bool(form.cleaned_data.get("id_document_held")),
                notes=form.cleaned_data.get("notes") or "",
                actor=self.request.user,
                allow_id_override=False,
            )
        except DomainError as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Giriş qeydə alındı.")
        return redirect("erp:reception")


class ReceptionStatusView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def post(self, request, pk):
        visit = get_object_or_404(GuestVisit.objects.select_related("guest"), pk=pk)
        action = request.POST.get("action")
        allow_override = user_has_permission(request.user, "reception.override_id")
        try:
            if action == "checkin":
                if not user_has_permission(request.user, "reception.check_in"):
                    raise PermissionDenied()
                ReceptionService.check_in_visit(
                    visit,
                    actor=request.user,
                    fin_code=request.POST.get("fin_code") or "",
                    first_name=request.POST.get("first_name") or "",
                    last_name=request.POST.get("last_name") or "",
                    id_document_held=request.POST.get("id_document_held") == "on",
                    id_override_reason=request.POST.get("id_override_reason") or "",
                    allow_id_override=allow_override,
                )
                messages.success(request, "Check-in tamamlandı.")
            elif action == "checkout":
                if not user_has_permission(request.user, "reception.check_out"):
                    raise PermissionDenied()
                id_returned = request.POST.get("id_returned", "on") == "on"
                ReceptionService.check_out_visit(
                    visit,
                    actor=request.user,
                    id_returned=id_returned,
                    allow_return_pending=allow_override and not id_returned,
                )
                messages.success(request, "Çıxış qeydə alındı.")
            elif action == "cancel":
                if not user_has_permission(request.user, "reception.cancel_visit"):
                    raise PermissionDenied()
                ReceptionService.cancel_visit(visit, actor=request.user)
                messages.success(request, "Ziyarət ləğv edildi.")
            elif action == "no_show":
                ReceptionService.mark_no_show(visit, actor=request.user)
                messages.success(request, "No-show qeydə alındı.")
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect("erp:reception")


class ReceptionGuestLookupView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def get(self, request):
        if not user_has_permission(request.user, "reception.search"):
            raise PermissionDenied()
        guest = ReceptionService.find_guest_by_fin(request.GET.get("fin", ""))
        if not guest:
            return JsonResponse({"found": False})
        can_sensitive = user_has_permission(request.user, "reception.view_sensitive_data")
        return JsonResponse(
            {
                "found": True,
                "first_name": guest.first_name,
                "last_name": guest.last_name,
                "phone": guest.phone,
                "fin": guest.fin_code if can_sensitive else mask_fin(guest.fin_code),
            }
        )


class ReceptionExportView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def get(self, request):
        if not user_has_permission(request.user, "reception.export"):
            raise PermissionDenied("Export icazəsi yoxdur.")
        can_sensitive = user_has_permission(request.user, "reception.view_sensitive_data")
        visits = today_visits_queryset().order_by("check_in_at", "created_at")
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "Guest",
                "FIN",
                "Company",
                "Host",
                "Type",
                "Check-in",
                "Check-out",
                "ID",
                "Access",
                "Status",
                "Invite",
            ]
        )
        for v in visits:
            fin = v.guest.fin_code if can_sensitive else mask_fin(v.guest.fin_code)
            access = getattr(v, "visitor_access", None)
            writer.writerow(
                [
                    v.guest.display_name,
                    fin,
                    v.company.name,
                    v.host.full_name if v.host_id else "",
                    v.visit_type.name if v.visit_type_id else "",
                    timezone.localtime(v.check_in_at).strftime("%H:%M") if v.check_in_at else "",
                    timezone.localtime(v.check_out_at).strftime("%H:%M") if v.check_out_at else "",
                    str(v.id_document_label),
                    access.status if access else "",
                    v.get_status_display(),
                    v.invite_code,
                ]
            )
        response = HttpResponse("\ufeff" + buf.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="visitors-{timezone.localdate().isoformat()}.csv"'
        )
        return response


class TicketListView(RoleRequiredMixin, ListView):
    template_name = "erp/tickets.html"
    context_object_name = "tickets"
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM)

    def get_queryset(self):
        qs = Ticket.objects.select_related(
            "category",
            "subcategory",
            "company",
            "space",
            "assignee",
            "queue",
            "department",
            "related_employee",
        )
        tab = self.request.GET.get("tab", "all")
        if tab == "open":
            qs = qs.filter(status__in=OPEN_STATUSES)
        elif tab == "sla":
            ids = [t.id for t in qs.filter(status__in=OPEN_STATUSES) if t.sla_risk]
            qs = qs.filter(id__in=ids)
        elif tab == "mine":
            qs = qs.filter(assignee=self.request.user)
        elif tab == "queue":
            qs = qs.filter(assignee__isnull=True, status__in=OPEN_STATUSES)
        elif tab == "card-orders":
            qs = qs.filter(subcategory__slug="card-order")
        if self.request.GET.get("department") == "security":
            qs = qs.filter(department__code="security")
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["tab"] = self.request.GET.get("tab", "all")
        return ctx


class TicketDetailView(RoleRequiredMixin, TemplateView):
    template_name = "erp/ticket_detail.html"
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM)

    def get_ticket(self):
        return get_object_or_404(
            Ticket.objects.select_related(
                "category",
                "subcategory",
                "company",
                "space",
                "assignee",
                "queue",
                "department",
                "opportunity",
                "related_employee",
            ).prefetch_related("attachments", "messages", "routing_events"),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ticket = self.get_ticket()
        ctx["ticket"] = ticket
        ctx["staff_users"] = User.objects.filter(
            role__in=[Role.SERVICE_DESK, Role.PROPERTY_FM, Role.ADMIN]
        )
        ctx["status_events"] = ticket.status_events.select_related("actor")
        ctx["routing_events"] = ticket.routing_events.select_related(
            "from_queue", "to_queue", "actor"
        )
        ctx["priorities"] = TicketPriority.choices
        from apps.maintenance.models import WorkOrder

        ctx["work_orders"] = WorkOrder.objects.filter(ticket=ticket)
        ctx["wo_eligible"] = ticket.wo_eligible
        ctx["crm_eligible"] = ticket.crm_eligible
        return ctx

    def post(self, request, *args, **kwargs):
        ticket = self.get_ticket()
        action = request.POST.get("action")
        if action == "advance" and ticket.next_status:
            advance_ticket_status(ticket, actor=request.user)
        elif action == "waiting":
            reason = request.POST.get("waiting_reason", "").strip()
            set_ticket_status(
                ticket, TicketStatus.WAITING, actor=request.user, note=reason, waiting_reason=reason
            )
        elif action == "close" and ticket.status == TicketStatus.RESOLVED:
            set_ticket_status(ticket, TicketStatus.CLOSED, actor=request.user)
        elif action == "reopen" and ticket.status in {
            TicketStatus.RESOLVED,
            TicketStatus.CLOSED,
        }:
            set_ticket_status(ticket, TicketStatus.REOPENED, actor=request.user, note="reopened")
        elif action == "cancel" and ticket.is_open:
            set_ticket_status(
                ticket, TicketStatus.CANCELLED, actor=request.user, note=request.POST.get("note", "")
            )
        elif action == "assign":
            assignee_id = request.POST.get("assignee")
            ticket.assignee_id = assignee_id or None
            ticket.save(update_fields=["assignee", "updated_at"])
            if ticket.assignee_id and ticket.status == TicketStatus.SENT:
                set_ticket_status(ticket, TicketStatus.ASSIGNED, actor=request.user, note="assigned")
        elif action == "priority":
            priority = request.POST.get("priority")
            if priority in dict(TicketPriority.choices):
                ticket.priority = priority
                ticket.save(update_fields=["priority", "updated_at"])
                apply_sla(ticket)
                messages.success(request, "Prioritet yeniləndi.")
        elif action == "enrich":
            notes = request.POST.get("enrichment_notes", "").strip()
            ticket.enrichment_notes = notes
            ticket.save(update_fields=["enrichment_notes", "updated_at"])
            messages.success(request, "Əlavə qeydlər saxlanıldı.")
        elif action == "attach":
            upload = request.FILES.get("file")
            if upload:
                from apps.tickets.models import TicketAttachment

                TicketAttachment.objects.create(ticket=ticket, file=upload)
                messages.success(request, "Fayl əlavə olundu.")
        elif action == "create_wo":
            from apps.maintenance.models import WorkOrder
            from apps.maintenance.services import create_wo_from_ticket

            if not ticket.wo_eligible:
                messages.error(request, "Bu ticket üçün Work Order yaradıla bilməz.")
            elif WorkOrder.objects.filter(ticket=ticket).exists():
                messages.info(request, "Work Order artıq mövcuddur.")
            else:
                wo = create_wo_from_ticket(ticket)
                messages.success(request, f"Work Order yaradıldı: {wo.code}")
        elif action == "create_crm":
            if not ticket.crm_eligible:
                messages.error(request, "Bu ticket üçün CRM ötürülməsi uyğun deyil.")
            elif ticket.opportunity_id:
                messages.info(request, "CRM Opportunity artıq bağlıdır.")
            else:
                opp = create_crm_opportunity_from_ticket(ticket, actor=request.user)
                messages.success(request, f"CRM Opportunity yaradıldı: {opp.title}")
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
                "active_residents": ResidentCompany.objects.filter(status="active", is_internal=False).count(),
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
        ctx["ticket_history"] = space.tickets.filter(status__in=CLOSED_STATUSES)
        ctx["all_tickets"] = space.tickets.select_related("category")[:20]
        ctx["assets"] = space.assets.all()
        ctx["documents"] = space.documents.all()
        ctx["employees"] = (
            space.resident.employees.filter(is_active=True) if space.resident_id else []
        )
        return ctx


class ResidentListView(StaffRequiredMixin, ListView):
    template_name = "erp/residents.html"
    queryset = ResidentCompany.objects.filter(is_internal=False)
    context_object_name = "companies"


class PartyListView(StaffRequiredMixin, ListView):
    """Master-data foundation UI for Party SoT (Scope 0)."""

    template_name = "erp/parties.html"
    queryset = Party.objects.prefetch_related("roles").order_by("legal_name")
    context_object_name = "parties"


class ResidentDetailView(StaffRequiredMixin, TemplateView):
    template_name = "erp/resident_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = get_object_or_404(ResidentCompany, slug=self.kwargs["slug"], is_internal=False)
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


class InternalStaffAccessView(RoleRequiredMixin, TemplateView):
    """City Point öz işçilərinin giriş/çıxışı — yalnız Admin / Rəhbərlik."""

    template_name = "erp/internal_staff_access.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)

    def get_company(self):
        return get_object_or_404(ResidentCompany, slug="city-point", is_internal=True)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        today = timezone.localdate()
        selected_date = parse_date(self.request.GET.get("date"), today)
        base = company.employees.all().order_by("full_name")
        employees, roster = employee_roster_qs(base, self.request.GET.get("roster"))
        rows, inside, left, present = build_employee_access_rows(employees, selected_date)
        ctx.update(
            {
                "company": company,
                "rows": rows,
                "inside": inside,
                "left": left,
                "present": present,
                "roster": roster,
                "today": today,
                "selected_date": selected_date,
                "is_today": selected_date == today,
            }
        )
        return ctx


class InternalStaffAccessDetailView(RoleRequiredMixin, TemplateView):
    template_name = "erp/internal_staff_access_detail.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)

    def get_employee(self):
        return get_object_or_404(
            ResidentEmployee,
            pk=self.kwargs["pk"],
            company__slug="city-point",
            company__is_internal=True,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        employee = self.get_employee()
        preset, date_from, date_to = access_range_bounds(self.request, default_preset="today")
        single_day = date_from == date_to
        if single_day:
            flaps = employee_day_flaps(employee, date_from)
            in_count = sum(1 for e in flaps if e.event_type == "in")
            out_count = len(flaps) - in_count
            days = []
        else:
            flaps = []
            days = employee_attendance_days(employee, date_from, date_to)
            in_count = out_count = 0
        ctx.update(
            {
                "employee": employee,
                "days": days,
                "flaps": flaps,
                "single_day": single_day,
                "preset": preset,
                "date_from": date_from,
                "date_to": date_to,
                "present_days": len(days) if not single_day else (1 if flaps else 0),
                "in_count": in_count,
                "out_count": out_count,
                "today": timezone.localdate(),
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
        from apps.billing.models import Invoice, InvoiceStatus
        from apps.crm.models import Lead, LeadStatus
        from apps.leases.models import Lease, LeaseStatus
        from apps.maintenance.models import WorkOrder, WorkOrderStatus
        from apps.property.models import CommercialStatus, Space
        from apps.warehouse.models import SKU, Stock

        open_tickets = list(Ticket.objects.filter(status__in=OPEN_STATUSES))
        spaces = Space.objects.all()
        vacant_m2 = sum(
            float(s.rentable_area_m2 or s.area_m2 or 0)
            for s in spaces.filter(commercial_status=CommercialStatus.VACANT)
        )
        total_m2 = sum(float(s.rentable_area_m2 or s.area_m2 or 0) for s in spaces) or 1
        occupied_m2 = total_m2 - vacant_m2
        low_stock = [
            st
            for st in Stock.objects.select_related("sku")
            if st.quantity <= (st.sku.reorder_level or 0)
        ]
        ctx.update(
            {
                "open_count": len(open_tickets),
                "sla_risk_count": sum(1 for t in open_tickets if t.sla_risk),
                "guest_count": GuestVisit.objects.filter(scheduled_for=timezone.localdate()).count(),
                "companies": ResidentCompany.objects.filter(status="active", is_internal=False),
                "occupancy_pct": round(100 * occupied_m2 / total_m2, 1),
                "vacant_m2": round(vacant_m2, 1),
                "leases_expiring": Lease.objects.filter(
                    status__in=[LeaseStatus.ACTIVE, LeaseStatus.EXPIRING]
                ).count(),
                "crm_new_leads": Lead.objects.filter(status=LeadStatus.NEW).count(),
                "open_wo": WorkOrder.objects.exclude(
                    status__in=[WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED]
                ).count(),
                "low_stock_count": len(low_stock),
                "receivable_count": Invoice.objects.filter(
                    status__in=[InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE]
                ).count(),
                "sku_count": SKU.objects.count(),
            }
        )
        return ctx


class LeaseListView(StaffRequiredMixin, ListView):
    template_name = "erp/leases.html"
    context_object_name = "leases"

    def get_queryset(self):
        from apps.leases.models import Lease

        return Lease.objects.select_related("party", "space").order_by("-created_at")


class LeaseDetailView(StaffRequiredMixin, TemplateView):
    template_name = "erp/lease_detail.html"

    def get_context_data(self, **kwargs):
        from apps.leases.models import Lease

        ctx = super().get_context_data(**kwargs)
        ctx["lease"] = get_object_or_404(Lease.objects.select_related("party", "space"), code=self.kwargs["code"])
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.leases.models import Lease
        from apps.leases.services import activate_lease, terminate_lease

        lease = get_object_or_404(Lease, code=kwargs["code"])
        action = request.POST.get("action")
        if action == "activate":
            activate_lease(lease, actor=request.user)
            messages.success(request, "Lease aktivləşdirildi.")
        elif action == "terminate":
            terminate_lease(lease, actor=request.user)
            messages.success(request, "Lease dayandırıldı.")
        return redirect("erp:lease_detail", code=lease.code)


class CrmLeadListView(StaffRequiredMixin, ListView):
    template_name = "erp/crm_leads.html"
    context_object_name = "leads"

    def get_queryset(self):
        from apps.crm.models import Lead

        return Lead.objects.select_related("interested_space", "party").order_by("-created_at")


class CrmOfferListView(StaffRequiredMixin, ListView):
    template_name = "erp/crm_offers.html"
    context_object_name = "offers"

    def get_queryset(self):
        from apps.crm.models import Offer

        return Offer.objects.select_related("party", "space", "opportunity", "lease").order_by("-id")


class WorkOrderListView(StaffRequiredMixin, ListView):
    template_name = "erp/work_orders.html"
    context_object_name = "work_orders"

    def get_queryset(self):
        from apps.maintenance.models import WorkOrder

        return WorkOrder.objects.select_related("space", "ticket", "asset").order_by("-created_at")


class WarehouseListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/warehouse.html"

    def get_context_data(self, **kwargs):
        from apps.warehouse.models import SKU, Stock, StockMovement

        ctx = super().get_context_data(**kwargs)
        stocks = list(Stock.objects.select_related("sku", "warehouse", "bin"))
        ctx.update(
            {
                "skus": SKU.objects.all()[:50],
                "stocks": stocks[:50],
                "movements": StockMovement.objects.select_related("sku", "warehouse")[:20],
                "low_stock": [s for s in stocks if s.quantity <= (s.sku.reorder_level or 0)],
            }
        )
        return ctx


class ProcurementListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement.html"

    def get_context_data(self, **kwargs):
        from apps.procurement.models import PurchaseOrder, PurchaseRequest

        ctx = super().get_context_data(**kwargs)
        ctx["prs"] = PurchaseRequest.objects.all()[:30]
        ctx["pos"] = PurchaseOrder.objects.select_related("supplier_party")[:30]
        return ctx


class BillingListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/billing.html"

    def get_context_data(self, **kwargs):
        from apps.billing.models import Charge, Invoice

        ctx = super().get_context_data(**kwargs)
        ctx["invoices"] = Invoice.objects.select_related("party", "lease")[:40]
        ctx["charges"] = Charge.objects.select_related("party", "lease")[:40]
        return ctx


class AccountingListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/accounting.html"

    def get_context_data(self, **kwargs):
        from apps.accounting.models import Account, JournalEntry

        ctx = super().get_context_data(**kwargs)
        ctx["accounts"] = Account.objects.all()[:50]
        ctx["journals"] = JournalEntry.objects.all()[:30]
        return ctx
