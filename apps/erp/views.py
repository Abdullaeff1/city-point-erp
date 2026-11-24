from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.generic import CreateView, DeleteView, FormView, ListView, TemplateView, UpdateView, View
import json

from apps.accounts.impersonation import can_start_impersonation, get_impersonator, is_impersonating
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.accounts.mixins import PermissionRequiredMixin, RoleRequiredMixin, StaffRequiredMixin
from apps.accounts.models import Role, User
from apps.accounts.routing import redirect_home
from apps.rbac.services import require_permission
from apps.core.services import DomainError
from apps.documents.models import Document
from apps.erp.forms import FloorForm, GuestVisitForm, SpaceForm, StaffTicketForm
from apps.property.models import (
    BuildingAsset,
    BuildingAssetCategory,
    BuildingAssetKind,
    CommercialStatus,
    Floor,
    OperationalStatus,
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
    employee_access_period_context,
    employee_attendance_days,
    employee_day_flaps,
    employee_roster_qs,
    parse_date,
)
from apps.residents.access_export import access_xlsx_http_response
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.residents.people_inside_export import (
    people_inside_company_count,
    people_inside_snapshot,
    people_inside_xlsx_http_response,
)
from apps.rbac.services import user_has_permission  # noqa: F401 — used throughout reception/leases
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
    WaitingReasonCode,
)
from apps.tickets.services import (
    add_message,
    advance_ticket_status,
    assign_ticket_employee,
    attach_ticket_file,
    citypoint_ticket_assignees,
    create_opportunity_from_ticket,
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
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        role = request.user.role
        if role == Role.RECEPTION:
            return redirect("erp:reception")
        if role == Role.SERVICE_DESK:
            return redirect("erp:supply_dashboard")
        if role == Role.ADMIN:
            # Prefer dedicated IT workspace; allow ?ops=1 for legacy ops panel.
            if request.GET.get("ops") != "1":
                return redirect("erp:it_dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        role = self.request.user.role
        from apps.rbac.services import user_has_permission

        if role == Role.SALES:
            if not user_has_permission(self.request.user, "crm.view"):
                raise PermissionDenied(_("CRM panelinə baxış icazəniz yoxdur."))
            from apps.crm.dashboard import build_sales_dashboard

            sales = build_sales_dashboard(self.request.user, self.request.GET)
            ctx.update(sales)
            ctx["is_sales_dashboard"] = True
            # Ops KPI must not be computed or passed for sales.
            return ctx

        if role == Role.MANAGEMENT:
            from apps.erp.department_dashboards import enhance_management_hub
            from apps.erp.management_hub import build_management_hub
            from apps.integrations.axtrax_health import axtrax_sync_health

            hub = enhance_management_hub(build_management_hub(self.request.user), self.request.user)
            ctx.update(hub)
            ctx["axtrax_health"] = axtrax_sync_health()
            return ctx

        today = timezone.localdate()
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
        pending_offers = 0
        pending_payments = 0
        pending_total = 0
        if role in {Role.ADMIN, Role.MANAGEMENT}:
            from apps.workflows.models import ApprovalRequest, ApprovalStatus

            pending = ApprovalRequest.objects.filter(
                workflow_code__in=("crm.offer.send", "finance.payment"),
                status=ApprovalStatus.PENDING,
            )
            pending_offers = pending.filter(workflow_code="crm.offer.send").count()
            pending_payments = pending.filter(workflow_code="finance.payment").count()
            pending_total = pending.count()
        ctx.update(
            {
                "is_sales_dashboard": False,
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
                    visible.filter(
                        status=TicketStatus.SENT,
                        assignee__isnull=True,
                        assigned_employee__isnull=True,
                    )[:5]
                    if show_tickets
                    else []
                ),
                "axtrax_health": axtrax,
                "pending_offers": pending_offers,
                "pending_payments": pending_payments,
                "pending_total": pending_total,
                "show_approvals": role in {Role.ADMIN, Role.MANAGEMENT},
            }
        )
        return ctx


class PeopleInsideView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    """Hal-hazırda binada olan əməkdaşlar + qonaqlar (bu gün).

    Presence is a Security/HR operational surface (includes City Point staff).
    Requires ``security.view`` or ``hr.view`` — not every ERP staff role.
    """

    template_name = "erp/people_inside.html"
    permission_required = ("security.view", "hr.view")
    permission_denied_message = "Binada olanlara baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        employees, guest_rows, today = people_inside_snapshot()
        ctx.update(
            {
                "today": today,
                "employee_rows": employees,
                "guest_rows": guest_rows,
                "inside_total": len(employees) + len(guest_rows),
                "inside_company_count": people_inside_company_count(employees, guest_rows),
            }
        )
        return ctx


class PeopleInsideExportView(PermissionRequiredMixin, StaffRequiredMixin, View):
    """Binada olanlar — Excel (şirkət adına görə)."""

    permission_required = ("security.view", "hr.view")
    permission_denied_message = "Binada olanlara baxış icazəniz yoxdur."

    def get(self, request):
        employees, guest_rows, today = people_inside_snapshot()
        return people_inside_xlsx_http_response(employees, guest_rows, report_date=today)


class PeopleInsideDetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    """Seçilmiş əməkdaşın bugünkü bütün kart eventləri."""

    template_name = "erp/people_inside_detail.html"
    permission_required = ("security.view", "hr.view")
    permission_denied_message = "Binada olanlara baxış icazəniz yoxdur."

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
    allow_management = False

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
            held = bool(form.cleaned_data.get("id_document_held"))
            allow_override = (not held) and user_has_permission(
                self.request.user, "reception.override_id"
            )
            ReceptionService.register_walk_in(
                fin_code=form.cleaned_data["fin_code"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                phone=form.cleaned_data.get("phone") or "",
                company=form.cleaned_data["company"],
                host=form.cleaned_data.get("host"),
                visit_type=form.cleaned_data.get("visit_type"),
                id_document_held=held,
                guest_card_number=form.cleaned_data.get("guest_card_number") or "",
                id_override_reason=form.cleaned_data.get("id_override_reason") or "",
                notes=form.cleaned_data.get("notes") or "",
                actor=self.request.user,
                allow_id_override=allow_override,
            )
        except DomainError as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Giriş qeydə alındı.")
        return redirect("erp:reception")


class ReceptionOverdueCheckoutView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)
    allow_management = False

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
    allow_management = False

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
            elif action == "return_id":
                if not user_has_permission(request.user, "reception.check_out"):
                    raise PermissionDenied()
                ReceptionService.complete_id_return(visit, actor=request.user)
                messages.success(request, "Vəsiqə qaytarıldı — ziyarət bağlandı.")
            elif action == "cancel":
                if not user_has_permission(request.user, "reception.cancel_visit"):
                    raise PermissionDenied()
                ReceptionService.cancel_visit(visit, actor=request.user)
                messages.success(request, "Ziyarət ləğv edildi.")
            elif action == "no_show":
                if not user_has_permission(request.user, "reception.cancel_visit"):
                    raise PermissionDenied()
                ReceptionService.mark_no_show(visit, actor=request.user)
                messages.success(request, "Gəlmədi qeydə alındı.")
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect("erp:reception")


class ReceptionVisitUpdateView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)
    allow_management = False

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
    allow_management = False

    def get(self, request):
        if not user_has_permission(request.user, "reception.create_visit"):
            raise PermissionDenied("Qonaq yaratmaq icazəsi yoxdur.")
        return guest_list_template_response()


class ReceptionGuestListPreviewView(RoleRequiredMixin, View):
    allowed_roles = (Role.RECEPTION,)
    allow_management = False

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
    allow_management = False

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
    allow_management = False

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
    allow_management = False

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
    allow_management = False

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
    allowed_roles = (Role.SERVICE_DESK, Role.SECURITY)

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
            # User assignee (Security) OR City Point employee matching this user's name (Service Desk).
            from django.db.models import Q

            name = (self.request.user.get_full_name() or "").strip()
            mine_q = Q(assignee=self.request.user)
            if name:
                mine_q |= Q(assigned_employee__full_name__iexact=name)
            qs = qs.filter(mine_q).distinct()
        elif tab == "queue":
            # Unassigned = neither User assignee nor ResidentEmployee worker.
            qs = qs.filter(
                assignee__isnull=True,
                assigned_employee__isnull=True,
                status__in=OPEN_STATUSES,
            )
        elif tab == "card-orders":
            qs = qs.filter(subcategory__slug="card-order")
        return qs

    def get_context_data(self, **kwargs):
        from datetime import timedelta

        from django.db.models import Q

        ctx = super().get_context_data(**kwargs)
        tab = self.request.GET.get("tab", "all")
        base = tickets_visible_to(self.request.user)
        open_qs = base.filter(status__in=OPEN_STATUSES)
        risk_at = timezone.now() + timedelta(hours=4)
        name = (self.request.user.get_full_name() or "").strip()
        mine_q = Q(assignee=self.request.user)
        if name:
            mine_q |= Q(assigned_employee__full_name__iexact=name)
        ctx["tab"] = tab
        ctx["ticket_tabs"] = [
            {"key": "all", "label": _("Hamısı"), "count": base.count()},
            {"key": "open", "label": _("Açıq"), "count": open_qs.count()},
            {
                "key": "queue",
                "label": _("Queue"),
                "count": open_qs.filter(
                    assignee__isnull=True, assigned_employee__isnull=True
                ).count(),
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
                "count": base.filter(mine_q).distinct().count(),
            },
        ]
        return ctx


class TicketCreateView(RoleRequiredMixin, FormView):
    template_name = "erp/ticket_create.html"
    form_class = StaffTicketForm
    allowed_roles = (Role.SERVICE_DESK,)
    allow_management = False

    def get_context_data(self, **kwargs):
        from apps.tickets.taxonomy_map import type_category_map_payload

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
        ctx["type_category_map"] = type_category_map_payload()
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
    allowed_roles = (Role.SERVICE_DESK,)

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
        ctx["waiting_reason_codes"] = WaitingReasonCode.choices
        ctx["work_orders"] = ticket.work_orders.select_related("contractor").order_by("-created_at")
        ctx["can_create_opportunity"] = bool(
            can_mutate_ticket(self.request.user, ticket)
            and ticket.crm_eligible
            and not ticket.opportunity_id
        )
        ctx["can_create_wo"] = bool(
            can_mutate_ticket(self.request.user, ticket) and ticket.wo_eligible
        )
        from apps.property.models import Contractor

        ctx["contractors"] = Contractor.objects.order_by("name")
        return ctx

    def post(self, request, *args, **kwargs):
        ticket = self.get_ticket()
        action = request.POST.get("action")
        try:
            if action == "advance" and ticket.next_status:
                note = (request.POST.get("resolution_note") or request.POST.get("note") or "").strip()
                from apps.tickets.models import TicketStatus as _TS
                from apps.tickets.services import set_ticket_status as _set_status

                if ticket.next_status == _TS.RESOLVED:
                    _set_status(ticket, _TS.RESOLVED, actor=request.user, note=note)
                else:
                    advance_ticket_status(ticket, actor=request.user)
            elif action == "waiting":
                reason = request.POST.get("waiting_reason", "").strip()
                reason_code = request.POST.get("waiting_reason_code", "").strip()
                set_ticket_status(
                    ticket,
                    TicketStatus.WAITING,
                    actor=request.user,
                    note=reason,
                    waiting_reason=reason,
                    waiting_reason_code=reason_code,
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
            elif action == "create_opportunity":
                opp = create_opportunity_from_ticket(ticket, actor=request.user)
                messages.success(request, f"Opportunity yaradıldı: {opp.title}")
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


class SpaceListView(PermissionRequiredMixin, StaffRequiredMixin, ListView):
    template_name = "erp/spaces.html"
    queryset = Space.objects.select_related("floor", "resident")
    context_object_name = "spaces"
    permission_required = "space.view"
    permission_denied_message = "Sahələrə baxış icazəniz yoxdur."

    def current_leases_by_space(self):
        from apps.leases.models import Lease, LeaseStatus

        if not user_has_permission(self.request.user, "lease.view"):
            return {}
        today = timezone.localdate()
        leases = (
            Lease.objects.filter(status__in=(LeaseStatus.ACTIVE, LeaseStatus.EXPIRING))
            .filter(
                Q(start_date__lte=today) | Q(start_date__isnull=True),
                Q(end_date__gte=today) | Q(end_date__isnull=True),
            )
            .select_related("party")
            .prefetch_related("lines")
            .order_by(F("end_date").asc(nulls_last=True), "-created_at")
        )
        by_space = {}
        for lease in leases:
            if lease.space_id:
                by_space.setdefault(lease.space_id, lease)
            for line in lease.lines.all():
                by_space.setdefault(line.space_id, lease)
        return by_space

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        floors = Floor.objects.select_related("building").prefetch_related("spaces__resident").order_by(
            "building__code", "code",
        )
        statuses = {
            "occupied": _("Dolu"),
            "vacant": _("Boş"),
            "reserved": CommercialStatus.RESERVED.label,
            "contracted": CommercialStatus.CONTRACTED.label,
            "maintenance": OperationalStatus.MAINTENANCE.label,
            "blocked": OperationalStatus.BLOCKED.label,
        }
        query = self.request.GET.get("q", "").strip()
        search = query.casefold()
        floor_filter = self.request.GET.get("floor", "")
        status_filter = self.request.GET.get("status", "")
        if status_filter not in statuses:
            status_filter = ""
        # Management building cards: lease/as-of inventory selectors (not register_status alone)
        mgmt = (self.request.GET.get("mgmt") or "").strip().lower()
        mgmt_ids = None
        mgmt_as_of = None
        if mgmt in {"rentable", "occupied"}:
            from apps.erp.exec_reports import build_property_report, parse_report_params

            as_of = (self.request.GET.get("as_of") or "").strip()
            params = parse_report_params({"date_to": as_of} if as_of else {})
            prop = build_property_report(params)
            mgmt_as_of = params["date_to"]
            if mgmt == "rentable":
                mgmt_ids = set(prop.get("denominator_ids") or [])
            else:
                mgmt_ids = {r["space_id"] for r in (prop.get("occupied_rows") or [])}
        filtering = bool(query or floor_filter or status_filter or mgmt_ids is not None)
        counts = dict.fromkeys(statuses, 0)
        current_leases = self.current_leases_by_space()
        floor_rows = []
        mgmt_visible_total = 0
        for floor in floors:
            spaces = floor.spaces.all()
            occupied = 0
            visible_spaces = []
            for space in spaces:
                status = space.register_status
                counts[status] += 1
                occupied += status == "occupied"
                lease = current_leases.get(space.pk) if status == "occupied" else None
                tenant = lease.party.display_name if lease else ""
                if not tenant and status == "occupied" and space.resident_id:
                    tenant = space.resident.name
                if floor_filter and floor_filter != str(floor.pk):
                    continue
                if status_filter and status_filter != status:
                    continue
                if mgmt_ids is not None and space.pk not in mgmt_ids:
                    continue
                if search and not any(
                    search in value.casefold() for value in (space.short_label, space.code, space.name, tenant)
                ):
                    continue
                visible_spaces.append({
                    "space": space, "status": status, "label": statuses[status], "tenant": tenant,
                    "lease_end": lease.end_date if lease else None,
                })
            mgmt_visible_total += len(visible_spaces)
            if visible_spaces or not filtering or (floor_filter == str(floor.pk) and not (search or status_filter or mgmt_ids is not None)):
                total = len(spaces)
                floor_rows.append({
                    "floor": floor, "total": total, "occupied": occupied,
                    "pct": occupied * 100 // total if total else 0, "spaces": visible_spaces,
                })
        space_count = sum(counts.values())
        ctx.update(
            {
                "floor_count": len(floors),
                "space_count": space_count,
                "occupied_count": counts["occupied"],
                "vacant_count": counts["vacant"],
                "occupancy_pct": counts["occupied"] * 100 // space_count if space_count else 0,
                "floor_rows": floor_rows,
                "floors": floors,
                "space_statuses": list(statuses.items()),
                "query": query,
                "floor_filter": floor_filter,
                "status_filter": status_filter,
                "filtering": filtering,
                "mgmt_filter": mgmt if mgmt_ids is not None else "",
                "mgmt_as_of": mgmt_as_of,
                "mgmt_filtered_count": mgmt_visible_total if mgmt_ids is not None else None,
                "can_manage_spaces": user_has_permission(self.request.user, "space.edit"),
            }
        )
        if ctx["can_manage_spaces"]:
            ctx["floor_form"] = FloorForm()
        return ctx


class FloorCreateView(PermissionRequiredMixin, StaffRequiredMixin, View):
    permission_required = "space.edit"
    permission_denied_message = "Sahə idarəetməsi icazəniz yoxdur."

    def post(self, request):
        form = FloorForm(request.POST)
        if form.is_valid():
            floor = form.save()
            messages.success(request, _("Mərtəbə əlavə olundu: %(code)s") % {"code": floor.code})
        else:
            err = "; ".join(e for errs in form.errors.values() for e in errs)
            messages.error(request, err or _("Mərtəbə əlavə olunmadı."))
        return redirect("erp:spaces")


class SpaceCreateView(PermissionRequiredMixin, StaffRequiredMixin, CreateView):
    template_name = "erp/space_form.html"
    form_class = SpaceForm
    model = Space
    permission_required = "space.edit"
    permission_denied_message = "Sahə idarəetməsi icazəniz yoxdur."

    def get_initial(self):
        initial = super().get_initial()
        floor_id = self.request.GET.get("floor")
        if floor_id and Floor.objects.filter(pk=floor_id).exists():
            initial["floor"] = floor_id
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = _("Sahə əlavə et")
        ctx["submit_label"] = _("Əlavə et")
        return ctx

    def form_valid(self, form):
        messages.success(self.request, _("Sahə yaradıldı: %(code)s") % {"code": form.instance.code})
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("erp:space_detail", kwargs={"code": self.object.code})


class SpaceUpdateView(PermissionRequiredMixin, StaffRequiredMixin, UpdateView):
    template_name = "erp/space_form.html"
    form_class = SpaceForm
    model = Space
    slug_field = "code"
    slug_url_kwarg = "code"
    permission_required = "space.edit"
    permission_denied_message = "Sahə idarəetməsi icazəniz yoxdur."

    def get_queryset(self):
        return Space.objects.select_related("floor", "resident")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = _("Sahəni düzəliş et")
        ctx["submit_label"] = _("Yadda saxla")
        ctx["space"] = self.object
        return ctx

    def form_valid(self, form):
        messages.success(self.request, _("Sahə yeniləndi."))
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("erp:space_detail", kwargs={"code": self.object.code})


class SpaceDeleteView(PermissionRequiredMixin, StaffRequiredMixin, DeleteView):
    model = Space
    slug_field = "code"
    slug_url_kwarg = "code"
    template_name = "erp/space_confirm_delete.html"
    permission_required = "space.edit"
    permission_denied_message = "Sahə idarəetməsi icazəniz yoxdur."
    success_url = "/erp/spaces/"

    def get_success_url(self):
        return reverse("erp:spaces")

    def form_valid(self, form):
        code = self.object.code
        messages.success(self.request, _("Sahə silindi: %(code)s") % {"code": code})
        return super().form_valid(form)


BUILDING_ASSET_VIEW_ROLES = {
    Role.SERVICE_DESK,
    Role.MANAGEMENT,
    Role.ADMIN,
    Role.ACCOUNTANT,
}


def can_mutate_building_assets(user) -> bool:
    return bool(user and user.is_authenticated and user.role == Role.ACCOUNTANT)


class BuildingAssetListView(LoginRequiredMixin, TemplateView):
    """Avadanlıq/inventar: baxış çoxrollu; əlavə/redaktə yalnız mühasib."""

    template_name = "erp/building_assets.html"
    asset_kind = BuildingAssetKind.EQUIPMENT
    list_url_name = "erp:building_equipment"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in BUILDING_ASSET_VIEW_ROLES:
            return redirect_home(request.user)
        # Mühasib ERP shell-ə düşməsin — finance portal URL-ə yönləndir
        if request.user.role == Role.ACCOUNTANT and str(self.list_url_name).startswith("erp:"):
            dest = (
                "finance:building_inventory"
                if self.asset_kind == BuildingAssetKind.INVENTORY
                else "finance:building_equipment"
            )
            return redirect(dest)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        if request.GET.get("template") == "1":
            if not can_mutate_building_assets(request.user):
                messages.error(request, _("Yalnız mühasib şablon yükləyə bilər."))
                return redirect(self.list_url_name)
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
        ctx["can_mutate_assets"] = can_mutate_building_assets(self.request.user)
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_mutate_building_assets(request.user):
            messages.error(request, _("Əlavə / redaktə yalnız mühasib üçündür."))
            return redirect(self.list_url_name)
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
            asset.manufacturer = (request.POST.get("manufacturer") or "").strip()
            asset.serial_number = (request.POST.get("serial_number") or "").strip()
            asset.warranty_until = parse_date(request.POST.get("warranty_until"), None)
            if request.FILES.get("document"):
                asset.document = request.FILES["document"]
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
        if request.FILES.get("document"):
            asset.document = request.FILES["document"]
        asset.save()
        from apps.property.models import BuildingAssetEvent, BuildingAssetEventType

        BuildingAssetEvent.objects.create(
            asset=asset,
            event_type=BuildingAssetEventType.INSTALL,
            summary="Qeydiyyata alındı",
            actor=request.user,
        )
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
        asset.manufacturer = (data.get("manufacturer") or "").strip()
        asset.serial_number = (data.get("serial_number") or "").strip()
        asset.warranty_until = parse_date(data.get("warranty_until"), None)
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


class SpaceDetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/space_detail.html"
    permission_required = "space.view"
    permission_denied_message = "Sahələrə baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        space = get_object_or_404(Space.objects.select_related("floor", "resident"), code=self.kwargs["code"])
        tab = self.request.GET.get("tab", "overview")
        from apps.property.drawings import user_can_manage_space_drawings
        from apps.property.models import SpaceDrawingKind, SpaceDrawingAccessStatus

        can_drawings = user_can_manage_space_drawings(self.request.user)
        if tab in {"dwg", "technical_plan"} and not can_drawings:
            tab = "overview"
        ctx["space"] = space
        ctx["tab"] = tab
        ctx["can_manage_drawings"] = can_drawings
        visible_space = tickets_visible_to(self.request.user).filter(space=space)
        ctx["open_tickets"] = visible_space.filter(status__in=OPEN_STATUSES)
        ctx["ticket_history"] = visible_space.filter(status__in=CLOSED_STATUSES)
        ctx["all_tickets"] = visible_space.select_related("category")[:20]
        ctx["assets"] = space.assets.all()
        ctx["documents"] = space.documents.select_related("company").all()
        ctx["employees"] = (
            space.resident.employees.filter(is_active=True) if space.resident_id else []
        )
        if can_drawings:
            drawings = space.drawings.all()
            ctx["dxf_drawings"] = drawings.filter(kind=SpaceDrawingKind.DXF)
            ctx["plan_drawings"] = drawings.filter(kind=SpaceDrawingKind.TECHNICAL_PLAN)
            ctx["pending_drawing_requests"] = (
                space.drawings.filter(access_requests__status=SpaceDrawingAccessStatus.PENDING)
                .distinct()
                .count()
            )
            from apps.property.models import SpaceDrawingAccessRequest

            ctx["space_pending_requests"] = (
                SpaceDrawingAccessRequest.objects.filter(
                    drawing__space=space,
                    status=SpaceDrawingAccessStatus.PENDING,
                )
                .select_related("user", "drawing")
                .order_by("created_at")
            )
        else:
            ctx["dxf_drawings"] = []
            ctx["plan_drawings"] = []
            ctx["pending_drawing_requests"] = 0
            ctx["space_pending_requests"] = []
        return ctx


def _can_view_resident_ops(user) -> bool:
    """Ticket drill-down — Admin / Rəhbərlik."""
    return user.role in {Role.ADMIN, Role.MANAGEMENT}


def _can_view_resident_guests(user) -> bool:
    """Resepsiya qeydləri — Admin, Rəhbərlik və Reception."""
    return user.role in {Role.ADMIN, Role.MANAGEMENT, Role.RECEPTION}


def _can_view_resident_ticket_counts(user) -> bool:
    """Şirkət siyahısındakı ticket sayı — Admin, Rəhbərlik və Service Desk."""
    return user.role in {Role.ADMIN, Role.MANAGEMENT, Role.SERVICE_DESK}


class ResidentListView(StaffRequiredMixin, ListView):
    template_name = "erp/residents.html"
    context_object_name = "companies"

    def get_queryset(self):
        from apps.core.search import filter_text_search
        from apps.erp.exec_reports import parse_report_params
        from apps.erp.management_hub import building_register_snapshot
        from apps.residents.permissions import user_can_manage_resident_profile

        show_archived = self.request.GET.get("archived") == "1"
        qs = ResidentCompany.objects.filter(is_internal=False).order_by("name")
        if show_archived:
            qs = qs.filter(is_archived=True)
        else:
            qs = qs.filter(is_archived=False)
        # Management building card: companies on register-occupied spaces
        if self.request.GET.get("occupying") == "1":
            as_of = (self.request.GET.get("as_of") or "").strip()
            params = parse_report_params({"date_to": as_of} if as_of else {})
            snap = building_register_snapshot(as_of=params["date_to"])
            company_ids = snap.get("occupying_resident_ids") or []
            qs = qs.filter(pk__in=company_ids)
            self._occupying_filter = True
            self._occupying_as_of = params["date_to"]
        else:
            self._occupying_filter = False
            self._occupying_as_of = None
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = filter_text_search(qs, q, "name", "slug", "contact_email", "voen")
        if _can_view_resident_ticket_counts(self.request.user):
            qs = qs.annotate(ticket_count=Count("tickets", distinct=True))
        # Subquery avoids join/filter Count edge cases and always yields an int.
        active_emp = (
            ResidentEmployee.objects.filter(company_id=OuterRef("pk"), is_active=True)
            .order_by()
            .values("company_id")
            .annotate(_c=Count("id"))
            .values("_c")[:1]
        )
        qs = qs.annotate(
            employee_count=Coalesce(Subquery(active_emp, output_field=IntegerField()), 0)
        )
        self._can_manage = user_can_manage_resident_profile(self.request.user)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q") or ""
        ctx["show_archived"] = self.request.GET.get("archived") == "1"
        ctx["occupying_filter"] = getattr(self, "_occupying_filter", False)
        ctx["occupying_as_of"] = getattr(self, "_occupying_as_of", None)
        ctx["can_view_resident_guests"] = _can_view_resident_guests(self.request.user)
        ctx["can_view_resident_ticket_counts"] = _can_view_resident_ticket_counts(self.request.user)
        ctx["company_opens_tickets"] = self.request.user.role == Role.SERVICE_DESK
        ctx["can_manage_resident"] = getattr(self, "_can_manage", False)
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
        from apps.erp.resident_views import enrich_resident_detail_context

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
        return enrich_resident_detail_context(self.request, company, ctx)


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

    def post(self, request, *args, **kwargs):
        from apps.residents.services import deactivate_resident_employee

        employee = self.get_employee()
        if request.POST.get("action") == "deactivate":
            if not employee.is_active:
                messages.info(request, _("Əməkdaş artıq deaktivdir."))
            else:
                deactivate_resident_employee(employee, actor=request.user, clear_card=True)
                messages.success(request, _("Əməkdaş deaktiv edildi (kart təmizləndi)."))
        return redirect(
            "erp:resident_employee_access",
            slug=employee.company.slug,
            pk=employee.pk,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        employee = self.get_employee()
        period = employee_access_period_context(employee, self.request, default_preset="today")
        ctx.update(
            {
                "employee": employee,
                "company": employee.company,
                "can_deactivate_employee": employee.is_active,
                **period,
            }
        )
        return ctx


class InternalStaffAccessView(PermissionRequiredMixin, RoleRequiredMixin, TemplateView):
    """City Point öz işçilərinin giriş/çıxışı — yalnız Admin / Rəhbərlik."""

    template_name = "erp/internal_staff_access.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)
    permission_required = "hr.view"
    permission_denied_message = "HR / daxili işçilərə baxış icazəniz yoxdur."
    page_size = 40

    def get_company(self):
        return get_object_or_404(ResidentCompany, slug="city-point")

    def get_context_data(self, **kwargs):
        from django.core.paginator import Paginator

        ctx = super().get_context_data(**kwargs)
        company = self.get_company()
        today = timezone.localdate()
        selected_date = parse_date(self.request.GET.get("date"), today)
        q = (self.request.GET.get("q") or "").strip()
        base = company.employees.all().order_by("full_name")
        if q:
            base = base.filter(Q(full_name__icontains=q) | Q(card_number__icontains=q))
        employees, roster = employee_roster_qs(base, self.request.GET.get("roster"))
        rows, inside, left, present = build_employee_access_rows(employees, selected_date)
        page = Paginator(rows, self.page_size).get_page(self.request.GET.get("page") or "1")
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
                "rows": page.object_list,
                "page_obj": page,
                "inside": inside,
                "left": left,
                "present": present,
                "roster": roster,
                "q": q,
                "today": today,
                "selected_date": selected_date,
                "is_today": selected_date == today,
                "export_preset": export_preset,
                "export_from": export_from,
                "export_to": export_to,
                "can_export_access": user_has_permission(
                    self.request.user, "residents.export_access"
                ),
                "total_employees": len(rows),
            }
        )
        return ctx


class InternalStaffAccessExportView(PermissionRequiredMixin, RoleRequiredMixin, View):
    """Admin/Management: Excel for City Point internal staff."""

    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)
    permission_required = "hr.view"
    permission_denied_message = "HR / daxili işçilərə baxış icazəniz yoxdur."

    def get(self, request, pk=None):
        if not user_has_permission(request.user, "residents.export_access"):
            raise PermissionDenied(_("Export icazəsi yoxdur."))
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


class InternalStaffAccessDetailView(PermissionRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = "erp/internal_staff_access_detail.html"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)
    permission_required = "hr.view"
    permission_denied_message = "HR / daxili işçilərə baxış icazəniz yoxdur."

    def get_employee(self):
        return get_object_or_404(
            ResidentEmployee,
            pk=self.kwargs["pk"],
            company__slug="city-point",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        employee = self.get_employee()
        period = employee_access_period_context(employee, self.request, default_preset="today")
        ctx.update(
            {
                "employee": employee,
                **period,
                "today": timezone.localdate(),
                "can_export_access": user_has_permission(
                    self.request.user, "residents.export_access"
                ),
            }
        )
        return ctx


class AuditLogView(StaffRequiredMixin, TemplateView):
    """Staff actions in one timeline. Real admin only, including role preview.

    Do not use PermissionRequiredMixin here: its require_permission() checks the
    effective (preview) user and would block Admin impersonation incorrectly.
    """

    template_name = "erp/audit.html"

    def dispatch(self, request, *args, **kwargs):
        from apps.erp.it_access import can_access_erp_audit

        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_erp():
            return redirect_home(request.user)
        if not can_access_erp_audit(request.user, request):
            raise PermissionDenied(_("Audit jurnalına baxış icazəniz yoxdur."))
        return super().dispatch(request, *args, **kwargs)

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


class DocumentsView(PermissionRequiredMixin, StaffRequiredMixin, ListView):
    template_name = "erp/documents.html"
    queryset = Document.objects.select_related("company", "space", "document_type")
    context_object_name = "documents"
    permission_required = "document.view"
    permission_denied_message = "Sənədlərə baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        from apps.documents.services import DocumentService
        from apps.rbac.services import user_has_permission

        ctx = super().get_context_data(**kwargs)
        docs = list(ctx["documents"])
        for doc in docs:
            doc.approval_info = DocumentService.approval_summary_for_document(doc)
        ctx["documents"] = docs
        ctx["can_submit_approval"] = user_has_permission(self.request.user, "document.edit")
        return ctx

    def post(self, request, *args, **kwargs):
        from django.core.exceptions import ValidationError

        from apps.documents.services import DocumentService
        from apps.rbac.services import require_permission

        require_permission(
            request.user,
            "document.edit",
            message=_("Sənəd təsdiqinə göndərmək üçün icazəniz yoxdur."),
        )
        action = request.POST.get("action")
        doc = get_object_or_404(Document, pk=request.POST.get("document_id"))
        try:
            if action == "submit_approval":
                DocumentService.submit_for_approval(doc, actor=request.user)
                messages.success(request, _("Sənəd Management təsdiqinə göndərildi."))
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except (DomainError, ValidationError) as exc:
            if hasattr(exc, "messages"):
                messages.error(request, "; ".join(exc.messages))
            else:
                messages.error(request, str(exc))
        return redirect("erp:documents")


class DocumentDownloadView(PermissionRequiredMixin, StaffRequiredMixin, View):
    """ACL-gated download for the document (optional historical version)."""

    permission_required = "document.view"
    permission_denied_message = "Sənədlərə baxış icazəniz yoxdur."

    def get(self, request, pk):
        from django.http import FileResponse, Http404

        from apps.documents.access import user_can_download_document
        from apps.documents.models import DocumentVersion

        document = get_object_or_404(Document, pk=pk)
        if not user_can_download_document(request.user, document):
            raise PermissionDenied(_("Bu sənədin məxfilik səviyyəsinə görə endirmə icazəniz yoxdur."))
        version_id = request.GET.get("version")
        file_field = document.file
        if version_id:
            version = get_object_or_404(DocumentVersion, pk=version_id, document=document)
            file_field = version.file or document.file
        if not file_field:
            raise Http404()
        try:
            handle = file_field.open("rb")
        except Exception as exc:
            raise Http404() from exc
        filename = (getattr(file_field, "name", "") or "document.bin").rsplit("/", 1)[-1]
        return FileResponse(handle, as_attachment=False, filename=filename)


class ReportsView(PermissionRequiredMixin, RoleRequiredMixin, TemplateView):
    """Phase 13 / M11 rəhbərlik hub — domain KPI + as-of filter + drill links."""

    template_name = "erp/reports.html"
    allowed_roles = (Role.MANAGEMENT, Role.ADMIN)
    permission_required = "report.view"
    permission_denied_message = "Hesabatlara baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        from apps.core.models import ReportSnapshot
        from apps.erp.exec_reports import build_exec_bundle, parse_report_params

        ctx = super().get_context_data(**kwargs)
        params = parse_report_params(self.request.GET)
        tab = (self.request.GET.get("tab") or "overview").strip()
        allowed = {
            "overview",
            "property",
            "crm",
            "sales",
            "service_desk",
            "fm",
            "warehouse",
            "finance",
            "security",
            "history",
        }
        if tab not in allowed:
            tab = "overview"
        bundle = build_exec_bundle(params, user=self.request.user)
        q = (
            f"date_from={params['date_from'].isoformat()}"
            f"&date_to={params['date_to'].isoformat()}"
        )
        if params.get("company_id"):
            q += f"&company_id={params['company_id']}"
        ctx.update(
            {
                "tab": tab,
                "params": params,
                "filter_qs": q,
                "bundle": bundle,
                "prop": bundle["property"],
                "crm": bundle["crm"],
                "sales": bundle["sales"],
                "service_desk": bundle["service_desk"],
                "fm": bundle["fm"],
                "warehouse": bundle["warehouse"],
                "finance": bundle["finance"],
                "security": bundle["security"],
                "companies": ResidentCompany.objects.filter(
                    status="active", is_internal=False
                ).order_by("name")[:200],
                "snapshots": ReportSnapshot.objects.filter(
                    company_id=params.get("company_id")
                ).order_by("-snapshot_date")[:30],
                "snapshot_missing_note": (
                    "Seçilmiş as-of üçün sətir yoxdursa capture edilməyib — "
                    "sonrakı reconstruction həmin günkü görünüş deyil."
                ),
                "occupancy_pct": bundle["property"]["occupancy_pct"],
                "vacant_m2": bundle["property"]["vacant_m2"],
                "open_count": bundle["service_desk"].get("open_count", 0),
                "sla_risk_count": bundle["service_desk"].get("open_risk", 0),
                "low_stock_count": bundle["warehouse"]["low_stock_count"],
                "crm_new_leads": bundle["crm"].get("lead_count", 0),
                "receivable_count": bundle["finance"].get("overdue_count", 0),
                "guest_count": GuestVisit.objects.filter(
                    scheduled_for=timezone.localdate()
                ).count(),
                "leases_expiring": bundle["property"]["leases_expiring_count"],
            }
        )
        return ctx


class ReportsExportView(RoleRequiredMixin, View):
    allowed_roles = (Role.MANAGEMENT, Role.ADMIN)

    def get(self, request, *args, **kwargs):
        from apps.erp.exec_reports import (
            build_exec_bundle,
            exec_report_xlsx_response,
            parse_report_params,
        )

        params = parse_report_params(request.GET)
        bundle = build_exec_bundle(params, user=request.user)
        return exec_report_xlsx_response(bundle)


class ReportsDrillView(PermissionRequiredMixin, RoleRequiredMixin, TemplateView):
    """KPI drill-down — same date/company scope; no Finance journal screen."""

    template_name = "erp/reports_drill.html"
    allowed_roles = (Role.MANAGEMENT, Role.ADMIN)
    permission_required = "report.view"
    permission_denied_message = "Hesabatlara baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        from apps.erp.exec_reports import (
            build_finance_report,
            build_fm_report,
            build_property_report,
            build_warehouse_report,
            parse_report_params,
        )

        ctx = super().get_context_data(**kwargs)
        params = parse_report_params(self.request.GET)
        section = (self.kwargs.get("section") or "property").strip()
        data = {}
        if section == "property":
            data = build_property_report(params)
        elif section == "finance":
            data = build_finance_report(params)
        elif section == "fm":
            data = build_fm_report(params)
        elif section == "warehouse":
            data = build_warehouse_report(params)
        else:
            section = "property"
            data = build_property_report(params)
        filter_qs = (
            f"date_from={params['date_from'].isoformat()}"
            f"&date_to={params['date_to'].isoformat()}"
            + (
                f"&company_id={params['company_id']}"
                if params.get("company_id")
                else ""
            )
        )
        ctx.update(
            {
                "section": section,
                "params": params,
                "data": data,
                "filter_qs": filter_qs,
                "next_page_url": (
                    f"?{filter_qs}&page={params['page'] + 1}"
                    if data.get("open_wo_has_more")
                    else ""
                ),
                "prev_page_url": (
                    f"?{filter_qs}&page={params['page'] - 1}"
                    if params.get("page", 1) > 1
                    else ""
                ),
            }
        )
        return ctx


class SlaReportView(RoleRequiredMixin, TemplateView):
    template_name = "erp/sla_report.html"
    allowed_roles = (Role.MANAGEMENT, Role.ADMIN, Role.SERVICE_DESK)

    def get_context_data(self, **kwargs):
        from apps.tickets.reporting import build_sla_report

        ctx = super().get_context_data(**kwargs)
        try:
            days = int(self.request.GET.get("days") or 30)
        except (TypeError, ValueError):
            days = 30
        days = max(7, min(days, 365))
        ctx["report"] = build_sla_report(
            queryset=tickets_visible_to(self.request.user),
            days=days,
        )
        return ctx


class SlaReportExportView(RoleRequiredMixin, View):
    allowed_roles = (Role.MANAGEMENT, Role.ADMIN, Role.SERVICE_DESK)

    def get(self, request, *args, **kwargs):
        from apps.tickets.reporting import build_sla_report, sla_report_xlsx_http_response

        try:
            days = int(request.GET.get("days") or 30)
        except (TypeError, ValueError):
            days = 30
        days = max(7, min(days, 365))
        report = build_sla_report(queryset=tickets_visible_to(request.user), days=days)
        return sla_report_xlsx_http_response(report)


class LeaseListView(StaffRequiredMixin, ListView):
    template_name = "erp/leases.html"
    context_object_name = "leases"

    def dispatch(self, request, *args, **kwargs):
        if not user_has_permission(request.user, "lease.view"):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        from datetime import timedelta

        from apps.leases.models import Lease

        qs = Lease.objects.select_related("party", "space").order_by("-created_at")
        filt = (self.request.GET.get("filter") or "").strip()
        if filt == "expiring":
            today = timezone.localdate()
            horizon = today + timedelta(days=90)
            qs = qs.filter(
                status__in=("active", "expiring"),
                end_date__isnull=False,
                end_date__gte=today,
                end_date__lte=horizon,
            ).order_by("end_date")
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lease_filter"] = (self.request.GET.get("filter") or "").strip()
        return ctx


class LeaseDetailView(StaffRequiredMixin, TemplateView):
    template_name = "erp/lease_detail.html"

    def dispatch(self, request, *args, **kwargs):
        if not user_has_permission(request.user, "lease.view"):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from apps.leases.models import Lease

        ctx = super().get_context_data(**kwargs)
        lease = get_object_or_404(
            Lease.objects.select_related("party", "space", "space__floor", "parent_lease").prefetch_related(
                "lines__space__floor", "deposit_settlements"
            ),
            code=self.kwargs["code"],
        )
        from apps.leases.services import lease_space_ids
        from apps.property.models import ParkingAssignment, UtilityMeter

        from apps.billing.models import Charge, ChargeSource
        from apps.accounts.models import Role

        ctx["lease"] = lease
        ctx["lease_lines"] = list(lease.lines.select_related("space", "space__floor"))
        ctx["deposit_settlements"] = list(lease.deposit_settlements.all()[:20])
        ctx["lease_addons"] = list(lease.addons.all())
        ctx["deposit_charges"] = list(
            Charge.objects.filter(lease=lease, source=ChargeSource.DEPOSIT).order_by("-pk")[:10]
        )
        ctx["recent_charges"] = list(
            Charge.objects.filter(lease=lease).exclude(source=ChargeSource.DEPOSIT).order_by("-pk")[:15]
        )
        ctx["can_view_finance"] = getattr(request_user := self.request.user, "role", None) in (
            Role.ACCOUNTANT,
            Role.ADMIN,
            Role.MANAGEMENT,
        ) or user_has_permission(self.request.user, "finance.view")
        space_ids = lease_space_ids(lease)
        parking_qs = ParkingAssignment.objects.filter(lease=lease).select_related(
            "spot", "spot__zone", "space", "employee"
        )
        if not parking_qs.exists() and (lease.party_id or space_ids):
            parking_qs = ParkingAssignment.objects.filter(
                Q(party_id=lease.party_id) | Q(space_id__in=space_ids)
            ).select_related("spot", "spot__zone", "space", "employee")
        ctx["parking_assignments"] = list(parking_qs[:50])
        ctx["utility_meters"] = (
            list(
                UtilityMeter.objects.filter(space_id__in=space_ids).select_related("space")[:50]
            )
            if space_ids
            else []
        )
        ctx["can_edit_lease"] = user_has_permission(self.request.user, "lease.edit")
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.leases.lease_ops import LeaseService, generate_monthly_lease_charges
        from apps.leases.models import DepositSettlement, Lease
        from apps.leases.services import activate_lease, terminate_lease

        if not user_has_permission(request.user, "lease.edit"):
            raise PermissionDenied
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
        elif action == "settle_deposit":
            kind = (request.POST.get("kind") or DepositSettlement.Kind.FULL_RETURN).strip()
            withhold = request.POST.get("withhold_amount") or 0
            reason = (request.POST.get("reason") or "").strip()
            LeaseService.settle_deposit(
                lease,
                kind=kind,
                withhold_amount=withhold,
                reason=reason,
            )
            messages.success(request, "Depozit hesablaşması yazıldı.")
        return redirect("erp:lease_detail", code=lease.code)


class CrmLeadListView(StaffRequiredMixin, ListView):
    template_name = "erp/crm_leads.html"
    context_object_name = "leads"

    def get_queryset(self):
        from apps.crm.models import Lead

        return Lead.objects.select_related("interested_space", "party").order_by("-created_at")

    def post(self, request, *args, **kwargs):
        # Obsolete stub — live CRM routes use apps.erp.crm_views.
        messages.error(
            request,
            "Bu köhnə CRM yolu bağlanıb. /erp/crm/leads/ üzərindən davam edin.",
        )
        return redirect("erp:crm_leads")


class CrmOfferListView(StaffRequiredMixin, ListView):
    template_name = "erp/crm_offers.html"
    context_object_name = "offers"

    def get_queryset(self):
        from apps.crm.models import Offer

        return Offer.objects.select_related("party", "space", "opportunity", "lease").order_by("-id")

    def post(self, request, *args, **kwargs):
        # Obsolete stub — live CRM routes use apps.erp.crm_views.
        messages.error(
            request,
            "Bu köhnə CRM yolu bağlanıb. /erp/crm/offers/ üzərindən davam edin.",
        )
        return redirect("erp:crm_offers")


# WarehouseListView moved to apps.erp.warehouse_views (Phase 4.4.2.2).


# ProcurementListView moved to apps.erp.procurement_views (Phase 4.4.2.3).


class BillingListView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/billing.html"
    permission_required = "finance.view"
    permission_denied_message = "Billing baxış icazəniz yoxdur."

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

        require_permission(
            request.user,
            "finance.edit",
            message=_("Billing əməliyyatı icazəniz yoxdur."),
        )
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
