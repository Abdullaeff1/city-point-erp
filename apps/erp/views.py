from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import FormView, ListView, TemplateView, View
import json

from apps.accounts.mixins import RoleRequiredMixin, StaffRequiredMixin
from apps.accounts.models import Role, User
from apps.core.services import DomainError
from apps.documents.models import Document
from apps.erp.forms import GuestVisitForm
from apps.property.models import Floor, Space
from apps.reception.guest_list_import import (
    PREVIEW_SESSION_KEY,
    commit_guest_list,
    guest_list_template_response,
    parse_guest_list_file,
    resolve_guest_rows,
)
from apps.reception.models import GuestListImport, GuestVisit, VisitStatus, mask_fin
from apps.reception.export import visits_xlsx_http_response
from apps.reception.services import (
    ReceptionService,
    filter_visits,
    id_pending_queryset,
    inside_overdue_queryset,
    today_visits_queryset,
    visits_queryset_for_range,
)
from apps.residents.access import (
    access_range_bounds,
    attendance_for_day,
    build_employee_access_rows,
    currently_inside_employee_rows,
    employee_attendance_days,
    employee_day_flaps,
    employee_roster_qs,
    parse_date,
)
from apps.residents.access_export import access_xlsx_http_response
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.rbac.services import user_has_permission
from apps.tickets.access import (
    can_handoff_ticket,
    can_mutate_ticket,
    department_assignees,
    tickets_visible_to,
)
from apps.tickets.models import (
    CLOSED_STATUSES,
    OPEN_STATUSES,
    Ticket,
    TicketDepartment,
    TicketPriority,
    TicketQueue,
    TicketStatus,
)
from apps.tickets.services import (
    add_message,
    advance_ticket_status,
    assign_ticket,
    attach_ticket_file,
    create_crm_opportunity_from_ticket,
    create_work_order_from_ticket,
    handoff_ticket,
    set_enrichment_notes,
    set_ticket_priority,
    set_ticket_status,
)


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "erp/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        role = self.request.user.role
        show_tickets = role != Role.RECEPTION
        open_list = []
        sla_tickets = []
        breached = []
        sla_ticket = None
        visible = tickets_visible_to(self.request.user)
        if show_tickets:
            open_qs = visible.filter(status__in=OPEN_STATUSES).select_related(
                "category", "company", "space"
            )
            open_list = list(open_qs)
            sla_tickets = [t for t in open_list if t.sla_risk]
            breached = [t for t in open_list if t.sla_breached]
            sla_ticket = breached[0] if breached else (sla_tickets[0] if sla_tickets else None)
        today_visits = GuestVisit.objects.filter(scheduled_for=today).select_related("guest", "company")
        guests_inside = today_visits.filter(status=VisitStatus.INSIDE).count()
        employees_inside = currently_inside_employee_rows(today)
        people_inside_count = len(employees_inside) + guests_inside
        activities = []
        if show_tickets:
            for t in visible.order_by("-updated_at")[:5]:
                activities.append({"at": t.updated_at, "text": f"{t.code} yeniləndi · {t.get_status_display()}"})
        for v in today_visits.filter(check_in_at__isnull=False).order_by("-check_in_at")[:4]:
            activities.append({"at": v.check_in_at, "text": f"Qonaq giriş etdi · {v.guest.display_name}"})
        activities.sort(key=lambda x: x["at"] or timezone.now(), reverse=True)
        axtrax = None
        if role in {Role.ADMIN, Role.MANAGEMENT}:
            from apps.integrations.axtrax_health import axtrax_sync_health

            axtrax = axtrax_sync_health()
        ctx.update(
            {
                "show_tickets": show_tickets,
                "guest_count": today_visits.count(),
                "open_count": len(open_list),
                "sla_risk_count": len(sla_tickets),
                "sla_breach_count": len(breached),
                "sla_ticket": sla_ticket,
                "new_residents": ResidentCompany.objects.filter(status="active", is_internal=False).count(),
                "people_inside_count": people_inside_count,
                "employees_inside_count": len(employees_inside),
                "guests_inside_count": guests_inside,
                "waiting_guests": today_visits.filter(
                    status__in=[VisitStatus.WAITING, VisitStatus.PRE_REGISTERED]
                ),
                "today_visits": today_visits[:8],
                "recent_open": open_list[:6],
                "activities": activities[:8],
                "unassigned": (
                    visible.filter(status=TicketStatus.SENT, assignee__isnull=True)[:5]
                    if show_tickets
                    else []
                ),
                "axtrax_health": axtrax,
            }
        )
        return ctx


class PeopleInsideView(StaffRequiredMixin, TemplateView):
    """Hal-hazırda binada olan əməkdaşlar + qonaqlar (bu gün)."""

    template_name = "erp/people_inside.html"

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
                "card_number": "",
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


class PeopleInsideDetailView(StaffRequiredMixin, TemplateView):
    """Seçilmiş əməkdaşın bugünkü bütün kart eventləri."""

    template_name = "erp/people_inside_detail.html"

    def get_employee(self):
        return get_object_or_404(
            ResidentEmployee.objects.select_related("company"),
            pk=self.kwargs["pk"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        employee = self.get_employee()
        today = timezone.localdate()
        flaps = employee_day_flaps(employee, today)
        in_at, out_at, status = attendance_for_day(flaps) if flaps else (None, None, "—")
        in_count = sum(1 for e in flaps if e.event_type == "in")
        out_count = len(flaps) - in_count
        ctx.update(
            {
                "employee": employee,
                "company": employee.company,
                "today": today,
                "flaps": flaps,
                "in_at": in_at,
                "out_at": out_at,
                "status": status,
                "in_count": in_count,
                "out_count": out_count,
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
        selected_date = parse_date(self.request.GET.get("date"), today)
        q = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "")
        company_id = self.request.GET.get("company") or ""
        id_not_returned = self.request.GET.get("id_not_returned") == "1"
        day_base = today_visits_queryset(selected_date)
        # "İçəridə indi" = bu gün hələ içəridə olanlar.
        # "24+ saat" = köhnə / uzun müddət bağlanmamış INSIDE qeydləri.
        if status == "inside_overdue":
            base = inside_overdue_queryset()
        elif status == "id_pending":
            base = id_pending_queryset()
        elif status == "inside":
            base = (
                today_visits_queryset(selected_date)
                .filter(status=VisitStatus.INSIDE)
                .order_by("check_in_at", "created_at")
            )
        else:
            base = day_base
        visits = filter_visits(
            base,
            q=q,
            status="" if status in {"inside", "inside_overdue", "id_pending"} else status,
            company_id=company_id or None,
            id_not_returned=id_not_returned,
        )
        can_sensitive = user_has_permission(self.request.user, "reception.view_sensitive_data")
        can_override = user_has_permission(self.request.user, "reception.override_id")
        can_export = user_has_permission(self.request.user, "reception.export")
        export_preset, export_from, export_to = access_range_bounds(
            self.request, default_preset="today"
        )
        inside_today_count = today_visits_queryset(today).filter(status=VisitStatus.INSIDE).count()
        inside_overdue_count = inside_overdue_queryset().count()
        stats = {
            "inside": inside_today_count,
            "inside_overdue": inside_overdue_count,
            "today": today_visits_queryset(today).count(),
            "day_total": day_base.count(),
            "waiting": today_visits_queryset(today).filter(
                status__in=[VisitStatus.WAITING, VisitStatus.PRE_REGISTERED]
            ).count(),
            "checked_out": day_base.filter(status=VisitStatus.LEFT).count(),
            "no_show": day_base.filter(status=VisitStatus.NO_SHOW).count(),
            "id_pending": id_pending_queryset().count(),
        }
        ctx.update(
            {
                "visits": visits,
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
                "today": today,
                "selected_date": selected_date,
                "is_today": selected_date == today,
                "export_preset": export_preset,
                "export_from": export_from,
                "export_to": export_to,
                "list_imports": (
                    GuestListImport.objects.filter(scheduled_for=selected_date)
                    .select_related("company")
                    .annotate(
                        guest_count=Count("visits"),
                        waiting_count=Count(
                            "visits",
                            filter=Q(
                                visits__status__in=[
                                    VisitStatus.PRE_REGISTERED,
                                    VisitStatus.WAITING,
                                ]
                            ),
                        ),
                    )
                ),
                "list_preview": self.request.session.get(PREVIEW_SESSION_KEY),
                "can_create_visit": user_has_permission(
                    self.request.user, "reception.create_visit"
                ),
                "can_check_in": user_has_permission(self.request.user, "reception.check_in"),
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
                visit_type=form.cleaned_data.get("visit_type"),
                id_document_held=bool(form.cleaned_data.get("id_document_held")),
                guest_card_number=form.cleaned_data.get("guest_card_number") or "",
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
                    guest_card_number=request.POST.get("guest_card_number") or "",
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


class ReceptionGuestListTemplateView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def get(self, request):
        if not user_has_permission(request.user, "reception.create_visit"):
            raise PermissionDenied("Qonaq yaratmaq icazəsi yoxdur.")
        return guest_list_template_response()


class ReceptionGuestListPreviewView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def post(self, request):
        if not user_has_permission(request.user, "reception.create_visit"):
            raise PermissionDenied("Qonaq yaratmaq icazəsi yoxdur.")
        uploaded = request.FILES.get("guest_list")
        if uploaded is None:
            messages.error(request, "Fayl seçin.")
            return redirect("erp:reception")
        company_raw = (request.POST.get("list_company") or "").strip()
        company_id = int(company_raw) if company_raw.isdigit() else None
        scheduled_for = parse_date(request.POST.get("list_date"), None)
        try:
            parsed = parse_guest_list_file(uploaded)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("erp:reception")
        except Exception:
            messages.error(request, "Fayl oxunmadı. Excel (.xlsx) və ya Word (.docx) göndərin.")
            return redirect("erp:reception")
        if not parsed:
            messages.error(request, "Siyahıda ad tapılmadı.")
            return redirect("erp:reception")
        companies = ResidentCompany.objects.filter(status="active", is_internal=False)
        rows = resolve_guest_rows(
            parsed,
            companies=companies,
            company_id=company_id,
            scheduled_for=scheduled_for,
        )
        request.session[PREVIEW_SESSION_KEY] = {
            "filename": uploaded.name,
            "rows": rows,
        }
        request.session.modified = True
        ready = sum(1 for row in rows if not row["error"])
        messages.success(request, f"{ready} nəfər yazılmağa hazırdır. Təsdiq edin.")
        target = scheduled_for
        if target is None:
            for row in rows:
                if row.get("scheduled_for"):
                    target = parse_date(row["scheduled_for"], None)
                    break
        if target is None:
            return redirect("erp:reception")
        return redirect(f"{redirect('erp:reception').url}?date={target.isoformat()}")


class ReceptionGuestListConfirmView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def post(self, request):
        if not user_has_permission(request.user, "reception.create_visit"):
            raise PermissionDenied("Qonaq yaratmaq icazəsi yoxdur.")
        preview = request.session.get(PREVIEW_SESSION_KEY)
        if request.POST.get("action") == "discard" or not preview:
            request.session.pop(PREVIEW_SESSION_KEY, None)
            if not preview:
                messages.error(request, "Önizləmə tapılmadı. Siyahını yenidən yükləyin.")
            return redirect("erp:reception")
        created = commit_guest_list(
            preview.get("rows") or [],
            filename=preview.get("filename") or "",
            actor=request.user,
        )
        request.session.pop(PREVIEW_SESSION_KEY, None)
        count = sum(item.visits.count() for item in created)
        if not count:
            messages.error(request, "Yazılacaq qonaq yoxdur.")
            return redirect("erp:reception")
        messages.success(request, f"{count} qonaq jurnala yazıldı.")
        return redirect(f"{redirect('erp:reception').url}?date={created[0].scheduled_for.isoformat()}")


class ReceptionGuestListCheckInView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def post(self, request, pk):
        if not user_has_permission(request.user, "reception.check_in"):
            raise PermissionDenied()
        list_import = get_object_or_404(GuestListImport, pk=pk)
        if list_import.scheduled_for > timezone.localdate():
            messages.error(request, "Giriş yalnız gəliş günü təsdiqlənir.")
            return redirect(f"{redirect('erp:reception').url}?date={list_import.scheduled_for.isoformat()}")
        try:
            count = ReceptionService.check_in_list(list_import, actor=request.user)
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect(f"{redirect('erp:reception').url}?date={list_import.scheduled_for.isoformat()}")
        if count:
            messages.success(request, f"{count} qonaq giriş etdi.")
        else:
            messages.error(request, "Gözləyən qonaq yoxdur.")
        return redirect(f"{redirect('erp:reception').url}?date={list_import.scheduled_for.isoformat()}")


class ReceptionGuestLookupView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def get(self, request):
        if not user_has_permission(request.user, "reception.search"):
            raise PermissionDenied()
        guest = ReceptionService.find_guest_by_fin(
            request.GET.get("serial")
            or request.GET.get("fin")
            or request.GET.get("q")
            or ""
        )
        if not guest:
            return JsonResponse({"found": False})
        can_sensitive = user_has_permission(request.user, "reception.view_sensitive_data")
        serial = guest.fin_code if can_sensitive else mask_fin(guest.fin_code)
        return JsonResponse(
            {
                "found": True,
                "first_name": guest.first_name,
                "last_name": guest.last_name,
                "phone": guest.phone,
                "serial": serial,
                "fin": serial,  # legacy alias
            }
        )


class ReceptionExportView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def get(self, request):
        if not user_has_permission(request.user, "reception.export"):
            raise PermissionDenied("Export icazəsi yoxdur.")
        can_sensitive = user_has_permission(request.user, "reception.view_sensitive_data")
        _preset, date_from, date_to = access_range_bounds(request, default_preset="today")
        visits = filter_visits(
            visits_queryset_for_range(date_from, date_to),
            q=request.GET.get("q", "").strip(),
            status=request.GET.get("status", ""),
            company_id=request.GET.get("company") or None,
            id_not_returned=request.GET.get("id_not_returned") == "1",
        ).order_by("scheduled_for", "check_in_at", "created_at")
        return visits_xlsx_http_response(
            visits,
            date_from,
            date_to,
            can_sensitive=can_sensitive,
        )


class TicketListView(RoleRequiredMixin, ListView):
    template_name = "erp/tickets.html"
    context_object_name = "tickets"
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM)

    def get_queryset(self):
        qs = tickets_visible_to(self.request.user).select_related(
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
            tickets_visible_to(self.request.user)
            .select_related(
                "category",
                "subcategory",
                "company",
                "space",
                "assignee",
                "queue",
                "department",
                "opportunity",
                "related_employee",
            )
            .prefetch_related("attachments", "messages", "routing_events"),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ticket = self.get_ticket()
        ctx["ticket"] = ticket
        ctx["staff_users"] = department_assignees(ticket)
        ctx["can_mutate"] = can_mutate_ticket(self.request.user, ticket)
        ctx["can_handoff"] = can_handoff_ticket(self.request.user, ticket)
        ctx["handoff_departments"] = TicketDepartment.objects.filter(is_active=True).order_by("name")
        ctx["handoff_queues"] = TicketQueue.objects.filter(is_active=True).select_related(
            "department"
        )
        ctx["status_events"] = ticket.status_events.select_related("actor")
        ctx["routing_events"] = ticket.routing_events.select_related(
            "from_queue", "to_queue", "from_department", "to_department", "actor"
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
            elif action == "cancel":
                set_ticket_status(
                    ticket,
                    TicketStatus.CANCELLED,
                    actor=request.user,
                    note=request.POST.get("note", ""),
                )
            elif action == "assign":
                assign_ticket(
                    ticket,
                    actor=request.user,
                    assignee_id=request.POST.get("assignee") or None,
                )
            elif action == "priority":
                set_ticket_priority(
                    ticket, actor=request.user, priority=request.POST.get("priority")
                )
                messages.success(request, "Prioritet yeniləndi.")
            elif action == "enrich":
                set_enrichment_notes(
                    ticket,
                    actor=request.user,
                    notes=request.POST.get("enrichment_notes", "").strip(),
                )
                messages.success(request, "Əlavə qeydlər saxlanıldı.")
            elif action == "attach":
                attach_ticket_file(ticket, actor=request.user, upload=request.FILES.get("file"))
                messages.success(request, "Fayl əlavə olundu.")
            elif action == "create_wo":
                wo = create_work_order_from_ticket(ticket, actor=request.user)
                messages.success(request, f"Work Order yaradıldı: {wo.code}")
            elif action == "create_crm":
                if not ticket.crm_eligible:
                    raise DomainError("Bu ticket üçün CRM ötürülməsi uyğun deyil.")
                if ticket.opportunity_id:
                    messages.info(request, "CRM Opportunity artıq bağlıdır.")
                else:
                    opp = create_crm_opportunity_from_ticket(ticket, actor=request.user)
                    messages.success(request, f"CRM Opportunity yaradıldı: {opp.title}")
            elif action == "handoff":
                handoff_ticket(
                    ticket,
                    actor=request.user,
                    department_id=request.POST.get("department"),
                    queue_id=request.POST.get("queue") or None,
                    note=request.POST.get("note", "").strip(),
                )
                messages.success(request, "Ticket digər şöbəyə yönləndirildi.")
            elif action == "message":
                body = request.POST.get("body", "").strip()
                if body:
                    add_message(
                        ticket, request.user, body, "CityPoint", require_mutate=True
                    )
        except DomainError as exc:
            messages.error(request, str(exc))
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
        visible_space = tickets_visible_to(self.request.user).filter(space=space)
        ctx["open_tickets"] = visible_space.filter(status__in=OPEN_STATUSES)
        ctx["ticket_history"] = visible_space.filter(status__in=CLOSED_STATUSES)
        ctx["all_tickets"] = visible_space.select_related("category")[:20]
        ctx["assets"] = space.assets.all()
        ctx["documents"] = space.documents.all()
        ctx["employees"] = (
            space.resident.employees.filter(is_active=True) if space.resident_id else []
        )
        return ctx


def _can_view_resident_ops(user) -> bool:
    """Ticket drill-down — Admin / Rəhbərlik."""
    return user.role in {Role.ADMIN, Role.MANAGEMENT}


def _can_view_resident_guests(user) -> bool:
    """Resepsiya qeydləri — Admin, Rəhbərlik və Reception."""
    return user.role in {Role.ADMIN, Role.MANAGEMENT, Role.RECEPTION}


class ResidentListView(StaffRequiredMixin, ListView):
    template_name = "erp/residents.html"
    context_object_name = "companies"

    def get_queryset(self):
        from apps.core.search import filter_text_search

        qs = ResidentCompany.objects.filter(is_internal=False).order_by("name")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = filter_text_search(qs, q, "name", "slug", "contact_email")
        if _can_view_resident_guests(self.request.user):
            today = timezone.localdate()
            qs = qs.annotate(
                guest_today=Count(
                    "guest_visits",
                    filter=Q(guest_visits__scheduled_for=today),
                )
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q") or ""
        ctx["can_view_resident_guests"] = _can_view_resident_guests(self.request.user)
        return ctx


def guest_period_query(preset, date_from, date_to) -> str:
    if preset == "custom":
        return f"range=custom&from={date_from.isoformat()}&to={date_to.isoformat()}"
    if preset == "today":
        return f"range=today&date={date_from.isoformat()}"
    return f"range={preset}"


def resident_guest_period(company, request):
    """Reception visits for one resident, filtered by scheduled_for.

    Counts come from the full queryset before any page slice.
    Unconfirmed portal pre-registrations stay in the set.
    """
    preset, date_from, date_to = access_range_bounds(request, default_preset="today")
    qs = company.guest_visits.filter(
        scheduled_for__gte=date_from,
        scheduled_for__lte=date_to,
    )
    counts = qs.aggregate(
        total=Count("id"),
        inside=Count("id", filter=Q(status=VisitStatus.INSIDE)),
        waiting=Count(
            "id",
            filter=Q(status__in=[VisitStatus.WAITING, VisitStatus.PRE_REGISTERED]),
        ),
        left=Count("id", filter=Q(status=VisitStatus.LEFT)),
    )
    return {
        "preset": preset,
        "date_from": date_from,
        "date_to": date_to,
        "single_day": date_from == date_to,
        "query": guest_period_query(preset, date_from, date_to),
        "qs": qs,
        "total": counts["total"],
        "inside": counts["inside"],
        "waiting": counts["waiting"],
        "left": counts["left"],
    }


class ResidentDetailView(StaffRequiredMixin, TemplateView):
    template_name = "erp/resident_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = get_object_or_404(ResidentCompany, slug=self.kwargs["slug"], is_internal=False)
        can_drill = _can_view_resident_ops(self.request.user)
        can_guests = _can_view_resident_guests(self.request.user)
        ctx.update(
            {
                "company": company,
                "spaces": company.spaces.select_related("floor"),
                "employees": company.employees.filter(is_active=True),
                "can_view_resident_ops": can_drill,
                "can_view_resident_guests": can_guests,
                "can_view_employees": can_drill,
            }
        )
        if can_guests:
            today = timezone.localdate()
            period = resident_guest_period(company, self.request)
            ctx.update(
                {
                    "today": today,
                    "guest_today": company.guest_visits.filter(scheduled_for=today).count(),
                    "guest_preset": period["preset"],
                    "guest_from": period["date_from"],
                    "guest_to": period["date_to"],
                    "guest_single_day": period["single_day"],
                    "guest_is_live_today": (
                        period["preset"] == "today" and period["date_from"] == today
                    ),
                    "guest_query": period["query"],
                    "guest_total": period["total"],
                    "guest_inside": period["inside"],
                    "guest_waiting": period["waiting"],
                    "guest_left": period["left"],
                }
            )
        return ctx


def _resident_company(slug):
    return get_object_or_404(ResidentCompany, slug=slug, is_internal=False)


class ResidentTicketsView(RoleRequiredMixin, TemplateView):
    """Şirkətin açıq ticket-ləri — Admin / Rəhbərlik."""

    template_name = "erp/resident_tickets.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = _resident_company(self.kwargs["slug"])
        tab = self.request.GET.get("tab", "open")
        qs = company.tickets.select_related(
            "category", "subcategory", "space", "assignee", "queue"
        ).order_by("-updated_at")
        if tab == "open":
            qs = qs.filter(status__in=OPEN_STATUSES)
        elif tab == "closed":
            qs = qs.filter(status__in=CLOSED_STATUSES)
        ctx.update({"company": company, "tickets": qs, "tab": tab})
        return ctx


class ResidentGuestsView(RoleRequiredMixin, TemplateView):
    """Şirkətin qonaq qeydləri — Admin, Rəhbərlik və Reception."""

    template_name = "erp/resident_guests.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT, Role.RECEPTION)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = _resident_company(self.kwargs["slug"])
        today = timezone.localdate()
        period = resident_guest_period(company, self.request)
        visits = period["qs"].select_related(
            "guest", "host", "visit_type", "visitor_access"
        ).order_by("-scheduled_for", "-check_in_at", "-id")
        ctx.update(
            {
                "company": company,
                "visits": visits,
                "visit_total": period["total"],
                "today": today,
                "preset": period["preset"],
                "date_from": period["date_from"],
                "date_to": period["date_to"],
                "single_day": period["single_day"],
                "guest_query": period["query"],
                "is_today": period["preset"] == "today" and period["date_from"] == today,
                "inside": period["inside"],
                "waiting": period["waiting"],
                "left": period["left"],
                "can_sensitive": user_has_permission(
                    self.request.user, "reception.view_sensitive_data"
                ),
            }
        )
        return ctx


class ResidentEmployeesAccessView(RoleRequiredMixin, TemplateView):
    """Tenant şirkət işçiləri + giriş/çıxış — Admin / Rəhbərlik."""

    template_name = "erp/resident_employees.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)

    def get_company(self):
        return _resident_company(self.kwargs["slug"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        today = timezone.localdate()
        selected_date = parse_date(self.request.GET.get("date"), today)
        base = company.employees.all().order_by("full_name")
        employees, roster = employee_roster_qs(base, self.request.GET.get("roster"))
        rows, inside, left, present = build_employee_access_rows(employees, selected_date)
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
                "roster": roster,
                "today": today,
                "selected_date": selected_date,
                "is_today": selected_date == today,
                "export_preset": export_preset,
                "export_from": export_from,
                "export_to": export_to,
                "can_export_access": user_has_permission(
                    self.request.user, "residents.export_access"
                ),
            }
        )
        return ctx


class ResidentAccessExportView(RoleRequiredMixin, View):
    """Admin/Management: Excel attendance for a resident company (optional one employee)."""

    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)

    def get(self, request, slug, pk=None):
        if not user_has_permission(request.user, "residents.export_access"):
            raise PermissionDenied("Export icazəsi yoxdur.")
        company = _resident_company(slug)
        preset, date_from, date_to = access_range_bounds(request, default_preset="month")
        employee = None
        if pk is not None:
            employee = get_object_or_404(
                ResidentEmployee,
                pk=pk,
                company=company,
                company__is_internal=False,
            )
        roster = (request.GET.get("roster") or "active").strip().lower()
        return access_xlsx_http_response(
            company,
            date_from,
            date_to,
            employee=employee,
            roster=roster,
        )


class ResidentEmployeeAccessDetailView(RoleRequiredMixin, TemplateView):
    """Əməkdaş giriş/çıxış detal — Admin / Rəhbərlik."""

    template_name = "erp/resident_employee_access_detail.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)

    def get_employee(self):
        return get_object_or_404(
            ResidentEmployee.objects.select_related("company"),
            pk=self.kwargs["pk"],
            company__slug=self.kwargs["slug"],
            company__is_internal=False,
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
                "company": employee.company,
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


class InternalStaffAccessView(RoleRequiredMixin, TemplateView):
    """City Point öz işçilərinin giriş/çıxışı — yalnız Admin / Rəhbərlik."""

    template_name = "erp/internal_staff_access.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)

    def get_company(self):
        return get_object_or_404(ResidentCompany, slug="city-point")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        today = timezone.localdate()
        selected_date = parse_date(self.request.GET.get("date"), today)
        base = company.employees.all().order_by("full_name")
        employees, roster = employee_roster_qs(base, self.request.GET.get("roster"))
        rows, inside, left, present = build_employee_access_rows(employees, selected_date)
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
                "roster": roster,
                "today": today,
                "selected_date": selected_date,
                "is_today": selected_date == today,
                "export_preset": export_preset,
                "export_from": export_from,
                "export_to": export_to,
            }
        )
        return ctx


class InternalStaffAccessExportView(RoleRequiredMixin, View):
    """Admin/Management: Excel for City Point internal staff."""

    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)

    def get(self, request, pk=None):
        if not user_has_permission(request.user, "residents.export_access"):
            raise PermissionDenied("Export icazəsi yoxdur.")
        company = get_object_or_404(ResidentCompany, slug="city-point")
        _preset, date_from, date_to = access_range_bounds(request, default_preset="month")
        employee = None
        if pk is not None:
            employee = get_object_or_404(
                ResidentEmployee,
                pk=pk,
                company=company,
            )
        roster = (request.GET.get("roster") or "active").strip().lower()
        return access_xlsx_http_response(
            company,
            date_from,
            date_to,
            employee=employee,
            roster=roster,
        )


class InternalStaffAccessDetailView(RoleRequiredMixin, TemplateView):
    template_name = "erp/internal_staff_access_detail.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)

    def get_employee(self):
        return get_object_or_404(
            ResidentEmployee,
            pk=self.kwargs["pk"],
            company__slug="city-point",
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

        open_tickets = list(
            tickets_visible_to(self.request.user).filter(status__in=OPEN_STATUSES)
        )
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
        from apps.leases.lease_ops import generate_monthly_lease_charges

        lease = get_object_or_404(Lease, code=kwargs["code"])
        action = request.POST.get("action")
        if action == "activate":
            activate_lease(lease, actor=request.user)
            messages.success(request, "Lease aktivləşdirildi.")
        elif action == "terminate":
            terminate_lease(lease, actor=request.user)
            messages.success(request, "Lease dayandırıldı.")
        elif action == "generate_charges":
            stats = generate_monthly_lease_charges()
            messages.success(request, f"Charges: created={stats['created']} skipped={stats['skipped']}")
        return redirect("erp:lease_detail", code=lease.code)


class CrmLeadListView(StaffRequiredMixin, ListView):
    template_name = "erp/crm_leads.html"
    context_object_name = "leads"

    def get_queryset(self):
        from apps.crm.models import Lead

        return Lead.objects.select_related("interested_space", "party").order_by("-created_at")

    def post(self, request, *args, **kwargs):
        from apps.crm.models import Lead
        from apps.crm.pipeline import CrmService

        lead = get_object_or_404(Lead, pk=request.POST.get("lead_id"))
        action = request.POST.get("action")
        if action == "qualify":
            CrmService.qualify_lead(lead)
            messages.success(request, "Lead qualified.")
        elif action == "opportunity":
            opp = CrmService.create_opportunity_from_lead(lead)
            messages.success(request, f"Opportunity #{opp.pk} yaradıldı.")
        return redirect("erp:crm_leads")


class CrmOfferListView(StaffRequiredMixin, ListView):
    template_name = "erp/crm_offers.html"
    context_object_name = "offers"

    def get_queryset(self):
        from apps.crm.models import Offer

        return Offer.objects.select_related("party", "space", "opportunity", "lease").order_by("-id")

    def post(self, request, *args, **kwargs):
        from apps.crm.models import Offer
        from apps.crm.pipeline import CrmService

        offer = get_object_or_404(Offer, pk=request.POST.get("offer_id"))
        if request.POST.get("action") == "to_lease":
            lease = CrmService.accept_offer_to_lease(offer)
            messages.success(request, f"Lease draft: {lease.code}")
            return redirect("erp:lease_detail", code=lease.code)
        return redirect("erp:crm_offers")


class WorkOrderListView(StaffRequiredMixin, ListView):
    template_name = "erp/work_orders.html"
    context_object_name = "work_orders"

    def get_queryset(self):
        from apps.maintenance.models import WorkOrder

        return WorkOrder.objects.select_related("space", "ticket", "asset").order_by("-created_at")

    def post(self, request, *args, **kwargs):
        from apps.maintenance.models import WorkOrder
        from apps.maintenance.services import WorkOrderService

        wo = get_object_or_404(WorkOrder, pk=request.POST.get("wo_id"))
        status = request.POST.get("status")
        if status:
            WorkOrderService.set_status(wo, status, actor=request.user)
            messages.success(request, f"{wo.code} → {status}")
        return redirect("erp:work_orders")


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

    def post(self, request, *args, **kwargs):
        from apps.procurement.services import ProcurementService
        from apps.warehouse.models import Stock

        if request.POST.get("action") == "create_pr":
            stock = get_object_or_404(Stock, pk=request.POST.get("stock_id"))
            pr = ProcurementService.create_pr_from_low_stock(stock=stock, requested_by=request.user)
            messages.success(request, f"PR yaradıldı: {pr.code}")
        return redirect("erp:warehouse")


class ProcurementListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement.html"

    def get_context_data(self, **kwargs):
        from apps.procurement.models import PurchaseOrder, PurchaseRequest

        ctx = super().get_context_data(**kwargs)
        ctx["prs"] = PurchaseRequest.objects.all()[:30]
        ctx["pos"] = PurchaseOrder.objects.select_related("supplier_party")[:30]
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.procurement.models import PurchaseOrder, PurchaseRequest
        from apps.procurement.services import ProcurementService
        from apps.warehouse.models import Warehouse

        action = request.POST.get("action")
        if action == "approve_pr":
            pr = get_object_or_404(PurchaseRequest, pk=request.POST.get("pr_id"))
            ProcurementService.approve_pr(pr, actor=request.user)
            messages.success(request, f"{pr.code} təsdiqləndi")
        elif action == "create_po":
            pr = get_object_or_404(PurchaseRequest, pk=request.POST.get("pr_id"))
            po = ProcurementService.create_po_from_pr(pr)
            messages.success(request, f"PO: {po.code}")
        elif action == "receive_po":
            po = get_object_or_404(PurchaseOrder, pk=request.POST.get("po_id"))
            wh = Warehouse.objects.first()
            if not wh:
                messages.error(request, "Warehouse yoxdur")
            else:
                ProcurementService.receive_po(po, warehouse=wh, actor=request.user)
                messages.success(request, f"{po.code} qəbul edildi")
        return redirect("erp:procurement")


class BillingListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/billing.html"

    def get_context_data(self, **kwargs):
        from apps.billing.models import Charge, Invoice

        ctx = super().get_context_data(**kwargs)
        ctx["invoices"] = Invoice.objects.select_related("party", "lease")[:40]
        ctx["charges"] = Charge.objects.filter(invoice__isnull=True).select_related("party")[:40]
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.billing.models import Charge
        from apps.billing.services import generate_invoice_from_charges
        from apps.leases.lease_ops import generate_monthly_lease_charges

        action = request.POST.get("action")
        if action == "generate_lease_charges":
            stats = generate_monthly_lease_charges()
            messages.success(request, f"Lease charges: {stats}")
        elif action == "invoice_party":
            party_id = request.POST.get("party_id")
            ids = list(
                Charge.objects.filter(party_id=party_id, invoice__isnull=True).values_list("pk", flat=True)[:50]
            )
            if ids:
                from apps.parties.models import Party

                party = get_object_or_404(Party, pk=party_id)
                inv = generate_invoice_from_charges(party, ids)
                messages.success(request, f"Invoice {inv.code}")
            else:
                messages.warning(request, "Uninvoiced charge yoxdur")
        return redirect("erp:billing")


class AccountingListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/accounting.html"

    def get_context_data(self, **kwargs):
        from apps.accounting.models import Account, JournalEntry

        ctx = super().get_context_data(**kwargs)
        ctx["accounts"] = Account.objects.all()[:50]
        ctx["journals"] = JournalEntry.objects.all()[:30]
        return ctx
