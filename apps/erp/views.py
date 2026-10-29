from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import FormView, ListView, TemplateView, View
import json

from apps.accounts.impersonation import can_start_impersonation, get_impersonator, is_impersonating
from apps.accounts.mixins import RoleRequiredMixin, StaffRequiredMixin
from apps.accounts.models import Role, User
from apps.core.services import DomainError
from apps.documents.models import Document
from apps.erp.forms import GuestVisitForm, StaffTicketForm
from apps.property.models import (
    BuildingAsset,
    BuildingAssetCategory,
    BuildingAssetKind,
    Floor,
    categories_for_kind,
    Space,
    add_one_month,
)
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
    can_delete_ticket,
    can_handoff_ticket,
    can_mutate_ticket,
    can_view_ticket,
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
    TicketSubcategory,
)
from apps.tickets.services import (
    add_message,
    advance_ticket_status,
    assign_ticket_employee,
    attach_ticket_file,
    citypoint_ticket_assignees,
    create_ticket_from_staff,
    create_work_order_from_ticket,
    delete_ticket,
    handoff_ticket,
    set_enrichment_notes,
    set_ticket_priority,
    set_ticket_status,
)


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "erp/dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role == Role.RECEPTION:
            return redirect("erp:reception")
        if request.user.is_authenticated and request.user.role == Role.SERVICE_DESK:
            return redirect("erp:tickets")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        role = self.request.user.role
        show_tickets = role != Role.RECEPTION
        show_guests = role != Role.SERVICE_DESK
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
        today_visits = GuestVisit.objects.none()
        guests_inside = 0
        employees_inside_count = 0
        people_inside_count = 0
        activities = []
        if show_guests:
            today_visits = GuestVisit.objects.filter(scheduled_for=today).select_related("guest", "company")
            guests_inside = today_visits.filter(status=VisitStatus.INSIDE).count()
            employees_inside_count = len(currently_inside_employee_rows(today))
            people_inside_count = employees_inside_count + guests_inside
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
                "show_guests": show_guests,
                "guest_count": today_visits.count(),
                "open_count": len(open_list),
                "sla_risk_count": len(sla_tickets),
                "sla_breach_count": len(breached),
                "sla_ticket": sla_ticket,
                "new_residents": ResidentCompany.objects.filter(status="active", is_internal=False).count(),
                "people_inside_count": people_inside_count,
                "employees_inside_count": employees_inside_count,
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
        export_preset, export_from, export_to = access_range_bounds(
            self.request, default_preset="today"
        )
        journal_single_day = export_from == export_to
        range_base = visits_queryset_for_range(export_from, export_to).order_by(
            "-scheduled_for", "-check_in_at", "-created_at"
        )
        # "İçəridə indi" = seçilmiş gün hələ içəridə olanlar.
        # "24+ saat" = köhnə / uzun müddət bağlanmamış INSIDE qeydləri.
        if status == "inside_overdue":
            base = inside_overdue_queryset()
        elif status == "id_pending":
            base = id_pending_queryset()
        elif status == "inside" and journal_single_day:
            base = (
                today_visits_queryset(export_from)
                .filter(status=VisitStatus.INSIDE)
                .order_by("check_in_at", "created_at")
            )
        elif status == "inside":
            base = range_base.filter(status=VisitStatus.INSIDE)
        else:
            base = range_base
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
        can_create_visit = user_has_permission(self.request.user, "reception.create_visit")
        guest_edits = []
        if can_create_visit:
            for visit in visits:
                try:
                    credential = visit.visitor_access.credential or ""
                except ObjectDoesNotExist:
                    credential = ""
                guest_edits.append(
                    {
                        "id": visit.pk,
                        "name": visit.guest.display_name,
                        "fin_code": visit.guest.fin_code if can_sensitive else "",
                        "first_name": visit.guest.first_name,
                        "last_name": visit.guest.last_name,
                        "company_id": visit.company_id,
                        "host_id": visit.host_id or "",
                        "visit_type_id": visit.visit_type_id or "",
                        "id_document_held": visit.id_document_held,
                        "guest_card_number": credential,
                        "notes": visit.notes or "",
                    }
                )
        inside_today_count = today_visits_queryset(today).filter(status=VisitStatus.INSIDE).count()
        inside_overdue_count = inside_overdue_queryset().count()
        stats = {
            "inside": inside_today_count,
            "inside_overdue": inside_overdue_count,
            "today": today_visits_queryset(today).count(),
            "day_total": range_base.count(),
            "waiting": today_visits_queryset(today).filter(
                status__in=[VisitStatus.WAITING, VisitStatus.PRE_REGISTERED]
            ).count(),
            "checked_out": range_base.filter(status=VisitStatus.LEFT).count(),
            "no_show": range_base.filter(status=VisitStatus.NO_SHOW).count(),
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
                "selected_date": export_from if export_preset == "today" else selected_date,
                "is_today": journal_single_day and export_from == today,
                "journal_single_day": journal_single_day,
                "show_visit_date": (not journal_single_day) or status in {"inside", "inside_overdue"},
                "export_preset": export_preset,
                "export_from": export_from,
                "export_to": export_to,
                "list_imports": (
                    GuestListImport.objects.filter(
                        scheduled_for__gte=export_from,
                        scheduled_for__lte=export_to,
                    )
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
                "guest_edits": guest_edits,
                "can_create_visit": can_create_visit,
                "can_check_in": user_has_permission(self.request.user, "reception.check_in"),
                "can_check_out": user_has_permission(self.request.user, "reception.check_out"),
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


class ReceptionOverdueCheckoutView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def post(self, request):
        if not user_has_permission(request.user, "reception.check_out"):
            raise PermissionDenied()
        qs = filter_visits(
            inside_overdue_queryset(),
            q=(request.POST.get("q") or "").strip(),
            company_id=request.POST.get("company") or None,
        )
        count = ReceptionService.check_out_visits(list(qs), actor=request.user)
        if count:
            messages.success(request, f"{count} qonaq çıxış etdi.")
        else:
            messages.error(request, "Çıxış ediləcək qonaq yoxdur.")
        return redirect(f"{reverse('erp:reception')}?status=inside_overdue")


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
                messages.success(request, "İçəri alma tamamlandı.")
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
                messages.success(request, "Gəlmədi qeydə alındı.")
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect("erp:reception")


class ReceptionVisitUpdateView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)

    def post(self, request, pk):
        if not user_has_permission(request.user, "reception.create_visit"):
            raise PermissionDenied("Qonaq məlumatını dəyişmək icazəsi yoxdur.")
        visit = get_object_or_404(GuestVisit.objects.select_related("guest"), pk=pk)
        form = GuestVisitForm(request.POST)
        if not form.is_valid():
            parts = [str(err) for errs in form.errors.values() for err in errs]
            messages.error(request, " ".join(parts) or "Qonaq məlumatı yenilənmədi.")
            return redirect(self._next(request))
        fin_code = form.cleaned_data.get("fin_code") or ""
        if not user_has_permission(request.user, "reception.view_sensitive_data"):
            fin_code = visit.guest.fin_code
        try:
            ReceptionService.update_visit_details(
                visit,
                fin_code=fin_code,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                company=form.cleaned_data["company"],
                host=form.cleaned_data.get("host"),
                visit_type=form.cleaned_data.get("visit_type"),
                id_document_held=bool(form.cleaned_data.get("id_document_held")),
                guest_card_number=form.cleaned_data.get("guest_card_number") or "",
                notes=form.cleaned_data.get("notes") or "",
                actor=request.user,
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect(self._next(request))
        messages.success(request, "Qonaq məlumatı yeniləndi.")
        return redirect(self._next(request))

    @staticmethod
    def _next(request):
        nxt = request.POST.get("next") or ""
        if nxt.startswith("/erp/reception"):
            return nxt
        return "erp:reception"


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
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM, Role.SECURITY)

    def get_queryset(self):
        qs = tickets_visible_to(self.request.user).select_related(
            "category",
            "subcategory",
            "company",
            "space",
            "assignee",
            "assigned_employee",
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
        from datetime import timedelta

        ctx = super().get_context_data(**kwargs)
        tab = self.request.GET.get("tab", "all")
        base = tickets_visible_to(self.request.user)
        open_qs = base.filter(status__in=OPEN_STATUSES)
        risk_at = timezone.now() + timedelta(hours=4)
        ctx["tab"] = tab
        ctx["ticket_tabs"] = [
            {"key": "all", "label": _("Hamısı"), "count": base.count()},
            {"key": "open", "label": _("Açıq"), "count": open_qs.count()},
            {
                "key": "queue",
                "label": _("Queue"),
                "count": open_qs.filter(assignee__isnull=True).count(),
            },
            {
                "key": "sla",
                "label": _("SLA risk"),
                "count": open_qs.filter(
                    sla_due_at__isnull=False,
                    sla_paused_at__isnull=True,
                    sla_due_at__lte=risk_at,
                ).count(),
            },
            {
                "key": "mine",
                "label": _("Mənim"),
                "count": base.filter(assignee=self.request.user).count(),
            },
        ]
        return ctx


class TicketCreateView(RoleRequiredMixin, FormView):
    template_name = "erp/ticket_create.html"
    form_class = StaffTicketForm
    allowed_roles = (Role.SERVICE_DESK, Role.PROPERTY_FM)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = ctx["form"]
        ctx["companies"] = [
            {"id": company.pk, "name": company.name}
            for company in form.fields["company"].queryset
        ]
        ctx["assignees"] = [
            {"id": employee.pk, "name": employee.full_name}
            for employee in form.fields["assigned_employee"].queryset
        ]
        ctx["spaces"] = [
            {
                "id": space.pk,
                "company_id": space.resident_id,
                "name": space.area_code,
            }
            for space in form.fields["space"].queryset
        ]
        ctx["subcategories"] = [
            {"id": sub.pk, "category_id": sub.category_id, "name": sub.name, "sort": sub.sort_order}
            for sub in TicketSubcategory.objects.filter(is_active=True).order_by("sort_order", "name")
        ]
        return ctx

    def form_valid(self, form):
        ticket = create_ticket_from_staff(
            actor=self.request.user,
            company=form.cleaned_data["company"],
            ticket_type=form.cleaned_data["ticket_type"],
            category=form.cleaned_data["category"],
            subcategory=form.cleaned_data["subcategory"],
            description=form.cleaned_data["description"],
            space=form.cleaned_data.get("space"),
            priority=form.cleaned_data.get("priority") or "",
            assigned_employee=form.cleaned_data.get("assigned_employee"),
        )
        messages.success(self.request, f"{ticket.code} yaradıldı.")
        if can_view_ticket(self.request.user, ticket):
            return redirect("erp:ticket_detail", code=ticket.code)
        messages.info(
            self.request,
            f"{ticket.code} {ticket.department} şöbəsinə yönləndirildi.",
        )
        return redirect("erp:tickets")


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
                "assigned_employee",
                "queue",
                "department",
                "related_employee",
            )
            .prefetch_related("attachments", "messages", "routing_events"),
            code=self.kwargs["code"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ticket = self.get_ticket()
        ctx["ticket"] = ticket
        ctx["can_mutate"] = can_mutate_ticket(self.request.user, ticket)
        ctx["can_delete"] = can_delete_ticket(self.request.user, ticket)
        ctx["assignee_choices"] = [
            {"id": employee.pk, "name": employee.full_name}
            for employee in citypoint_ticket_assignees()
        ]
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
        ctx["work_orders"] = ticket.work_orders.select_related("contractor").order_by("-created_at")
        from apps.property.models import Contractor

        ctx["contractors"] = Contractor.objects.order_by("name")
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
                assign_ticket_employee(
                    ticket,
                    actor=request.user,
                    employee_id=request.POST.get("assignee") or None,
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
            elif action == "handoff":
                handoff_ticket(
                    ticket,
                    actor=request.user,
                    department_id=request.POST.get("department"),
                    queue_id=request.POST.get("queue") or None,
                    note=request.POST.get("note", "").strip(),
                )
                messages.success(request, "Müraciət digər şöbəyə yönləndirildi.")
            elif action == "create_wo":
                wo = create_work_order_from_ticket(
                    ticket,
                    actor=request.user,
                    contractor_id=request.POST.get("contractor") or None,
                )
                messages.success(request, f"{wo.code} yaradıldı. Ticket öz şöbəsində qalır.")
                return redirect("erp:work_order_detail", code=wo.code)
            elif action == "message":
                body = request.POST.get("body", "").strip()
                if body:
                    add_message(
                        ticket, request.user, body, "CityPoint", require_mutate=True
                    )
            elif action == "delete":
                code = delete_ticket(ticket, actor=request.user)
                messages.success(request, f"{code} silindi.")
                return redirect("erp:tickets")
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


class BuildingAssetListView(RoleRequiredMixin, TemplateView):
    template_name = "erp/building_assets.html"
    allowed_roles = (Role.PROPERTY_FM, Role.SERVICE_DESK)
    asset_kind = BuildingAssetKind.EQUIPMENT
    list_url_name = "erp:building_equipment"

    def get(self, request, *args, **kwargs):
        if request.GET.get("template") == "1":
            from apps.property.asset_import import asset_template_response

            return asset_template_response(kind=self.asset_kind)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from apps.property.asset_import import session_key_for

        ctx = super().get_context_data(**kwargs)
        ctx["asset_kind"] = self.asset_kind
        ctx["list_url_name"] = self.list_url_name
        ctx["page_title"] = (
            "İnventarlar" if self.asset_kind == BuildingAssetKind.INVENTORY else "Avadanlıqlar"
        )
        ctx["item_label"] = (
            "inventar" if self.asset_kind == BuildingAssetKind.INVENTORY else "avadanlıq"
        )
        ctx["assets"] = BuildingAsset.objects.select_related("floor").filter(
            is_active=True, kind=self.asset_kind
        )
        ctx["floors"] = Floor.objects.order_by("code")
        ctx["categories"] = categories_for_kind(self.asset_kind)
        ctx["today"] = timezone.localdate()
        ctx["import_preview"] = self.request.session.get(session_key_for(self.asset_kind)) or []
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action") or ""
        if action in {"import", "import_save", "import_cancel"}:
            return self._import_post(request, action)
        if action == "update":
            asset = get_object_or_404(
                BuildingAsset,
                pk=request.POST.get("asset_id"),
                is_active=True,
                kind=self.asset_kind,
            )
            if not (request.POST.get("name") or "").strip():
                messages.error(request, "Ad yazılmayıb.")
                return redirect(self.list_url_name)
            asset.name = request.POST.get("name").strip()
            asset.location = (request.POST.get("location") or "").strip()
            asset.last_inspected_on = parse_date(request.POST.get("last_inspected_on"), None)
            posted_next = parse_date(request.POST.get("next_inspection_on"), None)
            if posted_next:
                asset.next_inspection_on = posted_next
            elif asset.last_inspected_on:
                asset.next_inspection_on = add_one_month(asset.last_inspected_on)
            else:
                asset.next_inspection_on = None
            asset.save()
            messages.success(
                request,
                "İnventar yeniləndi."
                if self.asset_kind == BuildingAssetKind.INVENTORY
                else "Avadanlıq yeniləndi.",
            )
            return redirect(self.list_url_name)
        if not (request.POST.get("name") or "").strip():
            messages.error(request, "Ad yazılmayıb.")
            return redirect(self.list_url_name)
        asset = BuildingAsset(name=request.POST.get("name").strip(), kind=self.asset_kind)
        self._apply_new(asset, request.POST)
        asset.save()
        messages.success(
            request,
            "İnventar əlavə olundu."
            if self.asset_kind == BuildingAssetKind.INVENTORY
            else "Avadanlıq əlavə olundu.",
        )
        return redirect(self.list_url_name)

    def _apply_new(self, asset, data):
        asset.kind = self.asset_kind
        asset.code = (data.get("code") or "").strip()
        allowed = {v for v, _ in categories_for_kind(self.asset_kind)}
        category = data.get("category") or BuildingAssetCategory.OTHER
        asset.category = category if category in allowed else BuildingAssetCategory.OTHER
        floor_id = (data.get("floor") or "").strip()
        asset.floor = Floor.objects.filter(pk=floor_id).first() if floor_id else None
        asset.location = (data.get("location") or "").strip()
        try:
            asset.quantity = max(1, int(data.get("quantity") or 1))
        except (TypeError, ValueError):
            asset.quantity = 1
        asset.notes = (data.get("notes") or "").strip()
        asset.last_inspected_on = parse_date(data.get("last_inspected_on"), None)
        posted_next = parse_date(data.get("next_inspection_on"), None)
        if posted_next:
            asset.next_inspection_on = posted_next
        elif asset.last_inspected_on:
            asset.next_inspection_on = add_one_month(asset.last_inspected_on)

    def _import_post(self, request, action):
        from apps.property.asset_import import (
            commit_asset_rows,
            parse_asset_file,
            preview_rows,
            session_key_for,
        )

        key = session_key_for(self.asset_kind)
        if action == "import_cancel":
            request.session.pop(key, None)
            return redirect(self.list_url_name)
        if action == "import_save":
            rows = request.session.get(key) or []
            if not rows:
                messages.error(request, "Yazılacaq sətir yoxdur.")
                return redirect(self.list_url_name)
            created, updated = commit_asset_rows(rows, kind=self.asset_kind)
            request.session.pop(key, None)
            messages.success(request, f"Əlavə olundu: {created}. Yeniləndi: {updated}.")
            return redirect(self.list_url_name)
        uploaded = request.FILES.get("asset_file")
        if not uploaded:
            messages.error(request, "Fayl seçilməyib.")
            return redirect(self.list_url_name)
        try:
            parsed = parse_asset_file(uploaded)
            rows = preview_rows(parsed, Floor.objects.order_by("code"), kind=self.asset_kind)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect(self.list_url_name)
        except Exception:
            messages.error(request, "Fayl oxunmadı. Excel (.xlsx) və ya Word (.docx) göndərin.")
            return redirect(self.list_url_name)
        if not rows:
            messages.error(request, "Faylda ad tapılmadı.")
            return redirect(self.list_url_name)
        request.session[key] = rows
        request.session.modified = True
        return redirect(self.list_url_name)


class BuildingEquipmentListView(BuildingAssetListView):
    asset_kind = BuildingAssetKind.EQUIPMENT
    list_url_name = "erp:building_equipment"


class BuildingInventoryListView(BuildingAssetListView):
    asset_kind = BuildingAssetKind.INVENTORY
    list_url_name = "erp:building_inventory"


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


def _can_view_resident_ticket_counts(user) -> bool:
    """Şirkət siyahısındakı ticket sayı — Admin və Service Desk."""
    return user.role in {Role.ADMIN, Role.SERVICE_DESK}


class ResidentListView(StaffRequiredMixin, ListView):
    template_name = "erp/residents.html"
    context_object_name = "companies"

    def get_queryset(self):
        from apps.core.search import filter_text_search

        qs = ResidentCompany.objects.filter(is_internal=False).order_by("name")
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = filter_text_search(qs, q, "name", "slug", "contact_email")
        if _can_view_resident_ticket_counts(self.request.user):
            qs = qs.annotate(ticket_count=Count("tickets", distinct=True))
        if _can_view_resident_guests(self.request.user):
            today = timezone.localdate()
            qs = qs.annotate(
                guest_today=Count(
                    "guest_visits",
                    filter=Q(guest_visits__scheduled_for=today),
                    distinct=True,
                )
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q") or ""
        ctx["can_view_resident_guests"] = _can_view_resident_guests(self.request.user)
        ctx["can_view_resident_ticket_counts"] = _can_view_resident_ticket_counts(self.request.user)
        ctx["company_opens_tickets"] = self.request.user.role == Role.SERVICE_DESK
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
    """Şirkətin ticket-ləri — Admin, Rəhbərlik və Service Desk."""

    template_name = "erp/resident_tickets.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT, Role.SERVICE_DESK)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = _resident_company(self.kwargs["slug"])
        tab = self.request.GET.get("tab", "open")
        qs = company.tickets.select_related(
            "category", "subcategory", "space", "assignee", "assigned_employee", "queue"
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


class AuditLogView(StaffRequiredMixin, TemplateView):
    """Staff actions in one timeline. Real admin only, including role preview."""

    template_name = "erp/audit.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_erp():
            raise PermissionDenied("ERP yalnız əməkdaşlar üçündür.")
        impersonator = get_impersonator(request)
        allowed = request.user.role == Role.ADMIN or (
            impersonator is not None and can_start_impersonation(impersonator)
        )
        if not allowed:
            raise PermissionDenied("Bu bölməyə giriş icazəniz yoxdur.")
        return super(StaffRequiredMixin, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from apps.audit.models import AuditLog
        from apps.audit.present import ROLE_ORDER, audit_rows, role_choices

        ctx = super().get_context_data(**kwargs)
        selected = (self.request.GET.get("role") or "").strip()
        if selected not in ROLE_ORDER:
            selected = ""
        logs = AuditLog.objects.select_related("actor").order_by("-created_at")
        if selected:
            logs = logs.filter(actor__role=selected)
        ctx["rows"] = audit_rows(list(logs[:500]))
        ctx["role"] = selected
        ctx["role_choices"] = role_choices()
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
            messages.success(request, "İcarə aktivləşdirildi.")
        elif action == "terminate":
            terminate_lease(lease, actor=request.user)
            messages.success(request, "İcarə dayandırıldı.")
        elif action == "generate_charges":
            stats = generate_monthly_lease_charges()
            messages.success(request, f"Ödənişlər: yaradıldı={stats['created']} keçildi={stats['skipped']}")
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
            messages.success(request, "Potensial müştəri uyğun sayıldı.")
        elif action == "opportunity":
            opp = CrmService.create_opportunity_from_lead(lead)
            messages.success(request, f"Fürsət #{opp.pk} yaradıldı.")
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
            messages.success(request, f"İcarə qaralaması: {lease.code}")
            return redirect("erp:lease_detail", code=lease.code)
        return redirect("erp:crm_offers")


class WarehouseListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/warehouse.html"

    def get_context_data(self, **kwargs):
        from apps.warehouse.models import SKU, Stock, StockMovement

        ctx = super().get_context_data(**kwargs)
        stocks = list(Stock.objects.select_related("sku", "warehouse", "bin"))
        from apps.warehouse.models import IssueStatus, WarehouseIssue
        from apps.warehouse.services import can_confirm_warehouse_issue

        ctx.update(
            {
                "skus": SKU.objects.all()[:50],
                "stocks": stocks[:50],
                "movements": StockMovement.objects.select_related("sku", "warehouse")[:20],
                "low_stock": [s for s in stocks if s.quantity <= (s.sku.reorder_level or 0)],
                "open_issues": WarehouseIssue.objects.filter(status=IssueStatus.OPEN)
                .select_related("work_order", "warehouse")
                .prefetch_related("lines__sku"),
                "can_confirm_issue": can_confirm_warehouse_issue(self.request.user),
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.procurement.services import ProcurementService
        from apps.warehouse.models import Stock, WarehouseIssue
        from apps.warehouse.services import can_confirm_warehouse_issue, confirm_issue
        from apps.core.services import DomainError

        action = request.POST.get("action")
        if action == "create_pr":
            stock = get_object_or_404(Stock, pk=request.POST.get("stock_id"))
            pr = ProcurementService.create_pr_from_low_stock(stock=stock, requested_by=request.user)
            messages.success(request, f"PR yaradıldı: {pr.code}")
        elif action == "confirm_issue":
            if not can_confirm_warehouse_issue(request.user):
                from django.core.exceptions import PermissionDenied

                raise PermissionDenied("Anbar çıxışını yalnız anbar təsdiqləyir.")
            issue = get_object_or_404(WarehouseIssue, pk=request.POST.get("issue_id"))
            posted = []
            missing = False
            for line in issue.lines.all():
                raw_qty = request.POST.get(f"issued_qty_{line.pk}")
                if raw_qty is None or str(raw_qty).strip() == "":
                    missing = True
                    break
                posted.append(
                    {
                        "id": line.pk,
                        "issued_qty": str(raw_qty).replace(",", "."),
                        "unit_cost": str(request.POST.get(f"unit_cost_{line.pk}") or "0").replace(",", "."),
                    }
                )
            if missing:
                messages.error(request, "Hər sətir üçün faktiki miqdar yazılmalıdır.")
                return redirect("erp:warehouse")
            try:
                confirm_issue(issue, actor=request.user, lines=posted)
                messages.success(request, f"{issue.code} üzrə çıxış təsdiqləndi.")
            except (DomainError, ValueError) as exc:
                messages.error(request, str(exc))
        return redirect("erp:warehouse")


class ProcurementListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/procurement.html"

    def get_context_data(self, **kwargs):
        from apps.procurement.models import PurchaseOrder, PurchaseRequest

        ctx = super().get_context_data(**kwargs)
        ctx["prs"] = PurchaseRequest.objects.all()[:30]
        ctx["pos"] = PurchaseOrder.objects.select_related("supplier_party", "pr").prefetch_related("lines")[:30]
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
        elif action == "set_line_price":
            from decimal import Decimal, InvalidOperation

            from apps.maintenance.costs import sync_procurement_cost
            from apps.procurement.models import POLine

            line = get_object_or_404(POLine.objects.select_related("po__pr"), pk=request.POST.get("line_id"))
            raw = str(request.POST.get("unit_price") or "0").strip().replace(" ", "").replace(",", ".")
            try:
                price = Decimal(raw)
            except InvalidOperation:
                messages.error(request, "Qiymət rəqəm olmalıdır.")
                return redirect("erp:procurement")
            if price < 0:
                messages.error(request, "Qiymət mənfi ola bilməz.")
                return redirect("erp:procurement")
            line.unit_price = price.quantize(Decimal("0.01"))
            line.save(update_fields=["unit_price"])
            if line.po.pr_id and line.po.pr.work_order_id:
                sync_procurement_cost(line.po.pr.work_order)
            messages.success(request, "Satınalma qiyməti saxlanıldı.")
        elif action == "receive_po":
            po = get_object_or_404(PurchaseOrder, pk=request.POST.get("po_id"))
            wh = Warehouse.objects.first()
            if not wh:
                messages.error(request, "Anbar yoxdur")
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
            messages.success(request, f"İcarə ödənişləri: {stats}")
        elif action == "invoice_party":
            party_id = request.POST.get("party_id")
            ids = list(
                Charge.objects.filter(party_id=party_id, invoice__isnull=True).values_list("pk", flat=True)[:50]
            )
            if ids:
                from apps.parties.models import Party

                party = get_object_or_404(Party, pk=party_id)
                inv = generate_invoice_from_charges(party, ids)
                messages.success(request, f"Faktura {inv.code}")
            else:
                messages.warning(request, "Fakturasız ödəniş yoxdur")
        return redirect("erp:billing")


class NotificationListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/alerts.html"

    def get(self, request, *args, **kwargs):
        from apps.comms.models import Notification

        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from apps.comms.links import user_notifications

        ctx = super().get_context_data(**kwargs)
        ctx["notifications"] = user_notifications(self.request.user, namespace="erp")
        ctx["unread_alerts"] = 0
        return ctx


class AccountingListView(StaffRequiredMixin, TemplateView):
    template_name = "erp/accounting.html"

    def get_context_data(self, **kwargs):
        from apps.accounting.models import Account, JournalEntry

        ctx = super().get_context_data(**kwargs)
        ctx["accounts"] = Account.objects.all()[:50]
        ctx["journals"] = JournalEntry.objects.all()[:30]
        return ctx
