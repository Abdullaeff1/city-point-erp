from datetime import timedelta
import json

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import FormView, ListView, TemplateView
from apps.accounts.mixins import ResidentChooserMixin, ResidentPortalMixin
from apps.accounts.portal_scope import (
    MODE_ALL,
    MODE_SINGLE,
    clear_portal_scope,
    eligible_companies_for,
    get_portal_scope,
    resolve_write_company,
    set_portal_scope,
)
from apps.comms.announcements import announcements_for_user
from apps.comms.models import Notification
from apps.core.services import DomainError
from apps.documents.models import Document
from apps.erp.forms import PortalEmployeeCreateForm, PortalTicketForm
from apps.reception.models import GuestVisit
from apps.reception.services import can_portal_checkout, portal_check_out_visit
from apps.residents.access import (
    access_range_bounds,
    build_employee_access_rows,
    employee_attendance_days,
    employee_day_flaps,
    employee_roster_qs,
    parse_date,
)
from apps.residents.access_export import access_xlsx_http_response
from apps.property.models import Space
from apps.residents.models import ResidentCompany, ResidentEmployee
from apps.residents.services import create_employee_card_order
from apps.tickets.access import can_delete_ticket
from apps.tickets.models import CLOSED_STATUSES, OPEN_STATUSES, Ticket, TicketAttachment, TicketSubcategory
from apps.tickets.services import add_message, create_ticket_from_portal, delete_ticket


def _scope_ids(request) -> list[int]:
    ids = getattr(request, "portal_company_ids", None)
    if ids is not None:
        return list(ids)
    scope = get_portal_scope(request)
    return list(scope.company_ids) if scope else []


def _scope_mode(request) -> str | None:
    scope = getattr(request, "portal_scope", None) or get_portal_scope(request)
    return scope.mode if scope else None


def _primary_display_company(request):
    ids = _scope_ids(request)
    if not ids:
        return None
    if _scope_mode(request) == MODE_SINGLE and len(ids) == 1:
        return ResidentCompany.objects.filter(pk=ids[0]).first()
    return None


class ChooseCompaniesView(ResidentChooserMixin, View):
    template_name = "portal/choose_companies.html"

    def get(self, request):
        # Clear previous scope so protected pages cannot be used until a new choice is POSTed
        clear_portal_scope(request)
        companies = eligible_companies_for(request.user)
        return render(
            request,
            self.template_name,
            {
                "companies": companies,
            },
        )

    def post(self, request):
        companies = eligible_companies_for(request.user)
        eligible_ids = {c.pk for c in companies}
        choice = (request.POST.get("choice") or "").strip()
        clear_portal_scope(request)

        if choice == "all":
            if len(companies) < 2:
                messages.error(request, _("Hamısı seçimi üçün ən azı iki şirkət lazımdır."))
                return render(request, self.template_name, {"companies": companies})
            set_portal_scope(request, MODE_ALL, [c.pk for c in companies])
            return redirect("portal:home")

        try:
            company_id = int(choice)
        except (TypeError, ValueError):
            messages.error(request, _("Şirkət seçin."))
            return render(request, self.template_name, {"companies": companies})

        if company_id not in eligible_ids:
            messages.error(request, _("Bu şirkətə icazəniz yoxdur."))
            return render(request, self.template_name, {"companies": companies})

        set_portal_scope(request, MODE_SINGLE, [company_id])
        return redirect("portal:home")


class HomeView(ResidentPortalMixin, TemplateView):
    template_name = "portal/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ids = _scope_ids(self.request)
        tickets = Ticket.objects.filter(company_id__in=ids) if ids else Ticket.objects.none()
        spaces = list(
            Space.objects.filter(resident_id__in=ids).select_related("floor", "resident")
        ) if ids else []
        latest = tickets.first()
        company = _primary_display_company(self.request)
        ctx.update(
            {
                "company": company,
                "portal_scope_all": _scope_mode(self.request) == MODE_ALL,
                "portal_company_count": len(ids),
                "spaces": spaces,
                "featured_space": spaces[0] if spaces else None,
                "open_tickets": tickets.filter(status__in=OPEN_STATUSES),
                "recent_tickets": tickets.select_related("company", "category")[:6],
                "latest_ticket": latest,
                "announcements": announcements_for_user(
                    self.request.user, company_ids=ids
                )[:4],
            }
        )
        return ctx


class SpacesView(ResidentPortalMixin, TemplateView):
    template_name = "portal/spaces.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ids = _scope_ids(self.request)
        ctx["spaces"] = (
            Space.objects.filter(resident_id__in=ids).select_related("floor", "resident")
            if ids
            else Space.objects.none()
        )
        ctx["show_company_column"] = _scope_mode(self.request) == MODE_ALL or len(ids) > 1
        return ctx


class SpaceDetailView(ResidentPortalMixin, TemplateView):
    """Resident space card — same tabs as ERP, scoped to portal companies."""

    template_name = "portal/space_detail.html"

    def get_space(self):
        ids = _scope_ids(self.request)
        if not ids:
            raise PermissionDenied
        return get_object_or_404(
            Space.objects.select_related("floor", "resident"),
            code=self.kwargs["code"],
            resident_id__in=ids,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        space = self.get_space()
        tab = self.request.GET.get("tab") or "overview"
        allowed_tabs = {
            "overview",
            "tickets",
            "documents",
            "employees",
            "assets",
            "dwg",
            "technical_plan",
        }
        if tab not in allowed_tabs:
            tab = "overview"
        company_tickets = Ticket.objects.filter(company_id=space.resident_id, space=space)
        from apps.property.models import (
            SpaceDrawingAccessRequest,
            SpaceDrawingAccessStatus,
            SpaceDrawingKind,
        )

        drawings = list(space.drawings.all())
        dxf = [d for d in drawings if d.kind == SpaceDrawingKind.DXF]
        plans = [d for d in drawings if d.kind == SpaceDrawingKind.TECHNICAL_PLAN]
        latest_by_drawing = {}
        for r in SpaceDrawingAccessRequest.objects.filter(
            user=self.request.user, drawing__space=space
        ).order_by("-created_at"):
            if r.drawing_id not in latest_by_drawing:
                latest_by_drawing[r.drawing_id] = r

        def annotate(rows):
            out = []
            for d in rows:
                r = latest_by_drawing.get(d.pk)
                can_dl = bool(r and r.is_download_allowed)
                out.append(
                    {
                        "drawing": d,
                        "request": r,
                        "can_download": can_dl,
                        "pending": bool(r and r.status == SpaceDrawingAccessStatus.PENDING),
                    }
                )
            return out

        ctx.update(
            {
                "space": space,
                "tab": tab,
                "open_tickets": company_tickets.filter(status__in=OPEN_STATUSES),
                "all_tickets": company_tickets.select_related("category")[:20],
                "assets": space.assets.all(),
                "documents": space.documents.all(),
                "employees": (
                    space.resident.employees.filter(is_active=True)
                    if space.resident_id
                    else ResidentEmployee.objects.none()
                ),
                "dxf_rows": annotate(dxf),
                "plan_rows": annotate(plans),
            }
        )
        return ctx


class PortalDrawingAccessRequestView(ResidentPortalMixin, View):
    def post(self, request, pk):
        ids = _scope_ids(request)
        from apps.property.drawings import request_drawing_access
        from apps.property.models import SpaceDrawing

        drawing = get_object_or_404(
            SpaceDrawing.objects.select_related("space"),
            pk=pk,
            space__resident_id__in=ids,
        )
        request_drawing_access(user=request.user, drawing=drawing)
        messages.success(request, _("İcazə sorğusu göndərildi."))
        tab = "dwg" if drawing.kind == "dxf" else "technical_plan"
        return redirect(f"{reverse('portal:space_detail', kwargs={'code': drawing.space.code})}?tab={tab}")


class PortalDrawingDownloadView(ResidentPortalMixin, View):
    def get(self, request, pk):
        ids = _scope_ids(request)
        from apps.property.drawings import user_may_download_drawing
        from apps.property.models import SpaceDrawing
        import mimetypes

        drawing = get_object_or_404(
            SpaceDrawing.objects.select_related("space"),
            pk=pk,
            space__resident_id__in=ids,
        )
        if not user_may_download_drawing(request.user, drawing):
            raise PermissionDenied(_("İcazə müddəti bitib və ya təsdiq olunmayıb."))
        if not drawing.file:
            raise PermissionDenied
        from django.http import FileResponse

        filename = drawing.original_name or drawing.file.name.rsplit("/", 1)[-1]
        content_type = drawing.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return FileResponse(
            drawing.file.open("rb"),
            as_attachment=True,
            filename=filename,
            content_type=content_type,
        )


class RequestCreateView(ResidentPortalMixin, FormView):
    template_name = "portal/request_new.html"
    form_class = PortalTicketForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        ids = _scope_ids(self.request)
        mode = _scope_mode(self.request)
        kwargs["companies"] = ResidentCompany.objects.filter(id__in=ids).order_by("name")
        kwargs["require_company"] = mode == MODE_ALL
        if mode == MODE_SINGLE and len(ids) == 1:
            kwargs["company"] = ResidentCompany.objects.filter(pk=ids[0]).first()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        mapping = {
            str(s.id): {"category_id": s.category_id, "name": s.name, "sort": s.sort_order}
            for s in TicketSubcategory.objects.filter(is_active=True)
            .order_by("sort_order", "name")
            .only("id", "category_id", "name", "sort_order")
        }
        ctx["subcategory_map_json"] = json.dumps(mapping, ensure_ascii=False)
        ctx["portal_scope_all"] = _scope_mode(self.request) == MODE_ALL
        return ctx

    def form_valid(self, form):
        company, err = resolve_write_company(
            self.request, form.cleaned_data.get("company").pk if form.cleaned_data.get("company") else None
        )
        if err or not company:
            form.add_error("company" if "company" in form.fields else None, err or _("Şirkət seçin."))
            return self.form_invalid(form)
        space = form.cleaned_data.get("space")
        if space and space.resident_id != company.id:
            form.add_error("space", _("Sahə seçilmiş şirkətə aid deyil."))
            return self.form_invalid(form)
        ticket = create_ticket_from_portal(
            company=company,
            requester=self.request.user,
            ticket_type=form.cleaned_data["ticket_type"],
            category=form.cleaned_data["category"],
            subcategory=form.cleaned_data["subcategory"],
            description=form.cleaned_data["description"],
            space=space,
            priority_suggestion=form.cleaned_data.get("resident_priority_suggestion") or "",
        )
        photo = form.cleaned_data.get("photo")
        if photo:
            TicketAttachment.objects.create(ticket=ticket, file=photo)
        return redirect("portal:request_detail", code=ticket.code)


class RequestListView(ResidentPortalMixin, ListView):
    template_name = "portal/request_list.html"
    context_object_name = "tickets"

    def get_queryset(self):
        ids = _scope_ids(self.request)
        if not ids:
            return Ticket.objects.none()
        qs = Ticket.objects.filter(company_id__in=ids).select_related("company", "category", "space")
        if self.kwargs.get("scope") == "active":
            qs = qs.filter(status__in=OPEN_STATUSES)
        elif self.kwargs.get("scope") == "history":
            qs = qs.filter(status__in=CLOSED_STATUSES)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["show_company_column"] = _scope_mode(self.request) == MODE_ALL
        return ctx


class RequestDetailView(ResidentPortalMixin, TemplateView):
    template_name = "portal/request_detail.html"

    def get_ticket(self):
        ids = _scope_ids(self.request)
        return get_object_or_404(
            Ticket.objects.prefetch_related("attachments").select_related("company", "space"),
            code=self.kwargs["code"],
            company_id__in=ids,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ticket = self.get_ticket()
        ctx["ticket"] = ticket
        ctx["can_delete"] = can_delete_ticket(self.request.user, ticket)
        return ctx

    def post(self, request, *args, **kwargs):
        ticket = self.get_ticket()
        action = request.POST.get("action")
        if action == "delete":
            try:
                code = delete_ticket(ticket, actor=request.user)
                messages.success(request, _("%(code)s silindi.") % {"code": code})
                return redirect("portal:requests_active")
            except DomainError as exc:
                messages.error(request, str(exc))
                return redirect("portal:request_detail", code=ticket.code)
        body = request.POST.get("body", "").strip()
        if body:
            add_message(ticket, request.user, body, "Siz")
        return redirect("portal:request_detail", code=ticket.code)


class AlertsView(ResidentPortalMixin, TemplateView):
    template_name = "portal/alerts.html"

    def get(self, request, *args, **kwargs):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        from apps.comms.links import user_notifications

        ids = _scope_ids(self.request)
        ctx["notifications"] = user_notifications(user, namespace="portal")
        ctx["history"] = Ticket.objects.filter(company_id__in=ids, status__in=CLOSED_STATUSES)
        ctx["unread_alerts"] = 0
        return ctx


class EmployeeAccessView(ResidentPortalMixin, TemplateView):
    template_name = "portal/employees.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ids = _scope_ids(self.request)
        companies = list(ResidentCompany.objects.filter(id__in=ids, is_internal=False))
        if not companies:
            ctx.update(
                {
                    "rows": [],
                    "inside": 0,
                    "left": 0,
                    "present": 0,
                    "roster": "active",
                    "today": timezone.localdate(),
                    "selected_date": timezone.localdate(),
                    "is_today": True,
                    "export_preset": "month",
                    "export_from": timezone.localdate().replace(day=1),
                    "export_to": timezone.localdate(),
                    "show_company_column": False,
                    "can_add_employee": False,
                }
            )
            return ctx
        today = timezone.localdate()
        selected_date = parse_date(self.request.GET.get("date"), today)
        base = (
            ResidentEmployee.objects.filter(company_id__in=[c.pk for c in companies])
            .select_related("company")
            .order_by("company__name", "full_name")
        )
        employees, roster = employee_roster_qs(base, self.request.GET.get("roster"))
        rows, inside, left, present = build_employee_access_rows(employees, selected_date)
        export_preset, export_from, export_to = access_range_bounds(
            self.request, default_preset="month"
        )
        if "range" not in self.request.GET:
            export_preset = "month"
            export_from = today.replace(day=1)
            export_to = today
        pending_ids = set(
            Ticket.objects.filter(
                company_id__in=[c.pk for c in companies],
                subcategory__slug="card-order",
                status__in=OPEN_STATUSES,
                related_employee_id__isnull=False,
            ).values_list("related_employee_id", flat=True)
        )
        for row in rows:
            emp = row["employee"]
            row["card_pending"] = (not emp.card_number) and (emp.pk in pending_ids)
        ctx.update(
            {
                "rows": rows,
                "inside": inside,
                "left": left,
                "present": present,
                "roster": roster,
                "today": today,
                "selected_date": selected_date,
                "is_today": selected_date == today,
                "can_add_employee": True,
                "export_preset": export_preset,
                "export_from": export_from,
                "export_to": export_to,
                "show_company_column": _scope_mode(self.request) == MODE_ALL or len(companies) > 1,
                "export_companies": companies,
            }
        )
        return ctx


class EmployeesAccessExportView(ResidentPortalMixin, View):
    """Download company (or one employee) attendance as Excel for the selected range."""

    def get(self, request, pk=None):
        ids = _scope_ids(request)
        if not ids:
            raise PermissionDenied
        preset, date_from, date_to = access_range_bounds(request, default_preset="month")
        employee = None
        if pk is not None:
            employee = get_object_or_404(
                ResidentEmployee,
                pk=pk,
                company_id__in=ids,
                company__is_internal=False,
            )
            company = employee.company
        else:
            company_id = request.GET.get("company")
            if company_id:
                try:
                    cid = int(company_id)
                except (TypeError, ValueError):
                    raise PermissionDenied
                if cid not in ids:
                    raise PermissionDenied
                company = get_object_or_404(ResidentCompany, pk=cid, is_internal=False)
            elif _scope_mode(request) == MODE_SINGLE and len(ids) == 1:
                company = get_object_or_404(ResidentCompany, pk=ids[0], is_internal=False)
            else:
                messages.error(request, _("Export üçün şirkət seçin."))
                return redirect("portal:employees")
        roster = (request.GET.get("roster") or "active").strip().lower()
        return access_xlsx_http_response(
            company,
            date_from,
            date_to,
            employee=employee,
            roster=roster,
        )


class EmployeeCreateView(ResidentPortalMixin, FormView):
    template_name = "portal/employee_create.html"
    form_class = PortalEmployeeCreateForm

    def dispatch(self, request, *args, **kwargs):
        # ResidentPortalMixin must run first so portal_company_ids is set
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.can_access_portal():
            raise PermissionDenied
        from apps.accounts.models import Role
        from apps.accounts.portal_scope import eligible_companies_for, require_portal_scope

        if request.user.role == Role.RESIDENT_USER:
            if not eligible_companies_for(request.user):
                raise PermissionDenied(_("Rezident şirkəti təyin olunmayıb və ya portal bağlıdır."))
            redir = require_portal_scope(request)
            if redir is not None:
                return redir
        else:
            require_portal_scope(request)

        ids = _scope_ids(request)
        companies = ResidentCompany.objects.filter(id__in=ids, is_internal=False)
        if not companies.exists():
            messages.error(request, _("Bu hesab üçün kart sifarişi edilə bilməz."))
            return redirect("portal:home")
        return FormView.dispatch(self, request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        ids = _scope_ids(self.request)
        mode = _scope_mode(self.request)
        kwargs["companies"] = ResidentCompany.objects.filter(id__in=ids, is_internal=False).order_by("name")
        kwargs["require_company"] = mode == MODE_ALL
        if mode == MODE_SINGLE and len(ids) == 1:
            kwargs["company"] = ResidentCompany.objects.filter(pk=ids[0]).first()
        return kwargs

    def form_valid(self, form):
        company, err = resolve_write_company(
            self.request,
            form.cleaned_data.get("company").pk if form.cleaned_data.get("company") else None,
        )
        if err or not company or company.is_internal:
            form.add_error("company" if "company" in form.fields else None, err or _("Şirkət seçin."))
            return self.form_invalid(form)
        try:
            employee, ticket = create_employee_card_order(
                company=company,
                requester=self.request.user,
                full_name=form.cleaned_data["full_name"],
                id_document=form.cleaned_data["id_document"],
                access_level=form.cleaned_data["access_level"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(
            self.request,
            _("“%(name)s” üçün kart sifarişi təhlükəsizliyə göndərildi (%(code)s). Kart AxTrax-da verildikdən sonra siyahıda görünəcək.")
            % {"name": employee.full_name, "code": ticket.code},
        )
        return redirect("portal:employees")


class EmployeeAccessDetailView(ResidentPortalMixin, TemplateView):
    template_name = "portal/employee_access_detail.html"

    def get_employee(self):
        ids = _scope_ids(self.request)
        return get_object_or_404(
            ResidentEmployee,
            pk=self.kwargs["pk"],
            company_id__in=ids,
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
                "list_url_name": "portal:employees",
                "detail_url_name": "portal:employee_access_detail",
            }
        )
        return ctx


class GuestsView(ResidentPortalMixin, FormView):
    template_name = "portal/guests.html"
    form_class = None  # set in get_form_class

    def get_form_class(self):
        from apps.erp.forms import PortalGuestForm

        return PortalGuestForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        ids = _scope_ids(self.request)
        mode = _scope_mode(self.request)
        kwargs["companies"] = ResidentCompany.objects.filter(id__in=ids).order_by("name")
        kwargs["require_company"] = mode == MODE_ALL
        if mode == MODE_SINGLE and len(ids) == 1:
            kwargs["company"] = ResidentCompany.objects.filter(pk=ids[0]).first()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ids = _scope_ids(self.request)
        days = int(self.request.GET.get("days") or 30)
        days = max(1, min(days, 365))
        since = timezone.localdate() - timedelta(days=days)
        ctx["guest_days"] = days
        ctx["show_company_column"] = _scope_mode(self.request) == MODE_ALL
        visits = (
            list(
                GuestVisit.objects.filter(company_id__in=ids, scheduled_for__gte=since)
                .select_related("guest", "host", "floor", "space", "visit_type", "visitor_access", "company")
                .order_by("-scheduled_for", "-id")[:100]
            )
            if ids
            else []
        )
        for v in visits:
            v.portal_can_checkout = can_portal_checkout(v, company=v.company)
        ctx["visits"] = visits
        return ctx

    def form_valid(self, form):
        from apps.reception.services import pre_register_visit

        company, err = resolve_write_company(
            self.request,
            form.cleaned_data.get("company").pk if form.cleaned_data.get("company") else None,
        )
        if err or not company:
            form.add_error("company" if "company" in form.fields else None, err or _("Şirkət seçin."))
            return self.form_invalid(form)
        host = form.cleaned_data.get("host")
        space = form.cleaned_data.get("space")
        if host and host.company_id != company.id:
            form.add_error("host", _("Host seçilmiş şirkətə aid deyil."))
            return self.form_invalid(form)
        if space and space.resident_id != company.id:
            form.add_error("space", _("Sahə seçilmiş şirkətə aid deyil."))
            return self.form_invalid(form)
        visit = pre_register_visit(
            company=company,
            first_name=form.cleaned_data["first_name"],
            last_name=form.cleaned_data["last_name"],
            email=form.cleaned_data.get("email") or "",
            phone=form.cleaned_data.get("phone") or "",
            host=host,
            space=space,
            location_note=form.cleaned_data.get("location_note") or "",
            visit_type=form.cleaned_data.get("visit_type"),
            portal_user=self.request.user,
        )
        if form.cleaned_data.get("expected_arrival"):
            visit.expected_arrival = form.cleaned_data["expected_arrival"]
            visit.scheduled_for = form.cleaned_data["expected_arrival"].date()
            visit.save(update_fields=["expected_arrival", "scheduled_for", "updated_at"])
        return redirect("portal:guests")


class GuestCheckoutView(ResidentPortalMixin, View):
    def post(self, request, pk):
        ids = _scope_ids(request)
        visit = get_object_or_404(
            GuestVisit.objects.select_related("guest", "visitor_access", "company"),
            pk=pk,
            company_id__in=ids,
        )
        try:
            portal_check_out_visit(visit, actor=request.user, company=visit.company)
            messages.success(request, _("Çıxış qeydə alındı."))
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect("portal:guests")


class AnnouncementsView(ResidentPortalMixin, ListView):
    template_name = "portal/announcements.html"
    context_object_name = "announcements"

    def get_queryset(self):
        return announcements_for_user(
            self.request.user, company_ids=_scope_ids(self.request)
        ).prefetch_related("attachments")


class DocumentsView(ResidentPortalMixin, ListView):
    template_name = "portal/documents.html"
    context_object_name = "documents"

    def get_queryset(self):
        ids = _scope_ids(self.request)
        return Document.objects.filter(Q(company_id__in=ids) | Q(company__isnull=True))
