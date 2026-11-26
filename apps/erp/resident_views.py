"""Resident company profile + documents CRUD (ERP)."""

from __future__ import annotations

import mimetypes

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, FormView, TemplateView, UpdateView

from django.db.models import Q

from apps.accounts.mixins import PermissionRequiredMixin, RoleRequiredMixin, StaffRequiredMixin
from apps.accounts.models import Role
from apps.documents.models import SEED_DOCUMENT_TYPES, Document, DocumentType
from apps.documents.services import DocumentService
from apps.erp.forms import RESIDENT_FORM_SECTIONS, ResidentCompanyForm, ResidentDocumentForm
from apps.maintenance.access import work_orders_queryset_for
from apps.residents.company_sync import (
    archive_resident_company,
    save_resident_company,
    unarchive_resident_company,
)
from apps.residents.lease_dates import lease_date_summary, lease_display_rows, parking_for_company
from apps.residents.models import ResidentCompany
from apps.residents.permissions import (
    user_can_manage_resident_profile,
    user_can_view_resident_directory,
    user_can_view_resident_legal_docs,
    user_is_reception_limited,
)
from apps.tickets.access import tickets_visible_to

SECTION_HUB = "hub"
SECTION_GENERAL = "general"
SECTION_CONTACTS = "contacts"
SECTION_BANK = "bank"
SECTION_LEASES = "leases"
SECTION_ACCESS = "access"
SECTION_DOCUMENTS = "documents"

LEGAL_SECTIONS = {SECTION_GENERAL, SECTION_CONTACTS, SECTION_BANK, SECTION_LEASES, SECTION_DOCUMENTS}


def _company(slug):
    return get_object_or_404(ResidentCompany, slug=slug, is_internal=False)


def _directory_office_kind(status: str) -> str:
    """Classify office link using Space.register_status (property SoT)."""
    if status == "occupied":
        return "occupied"
    if status in {"reserved", "contracted"}:
        return "reserved"
    # Vacant / maintenance / blocked while still linked → historical or non-current
    return "historical"


def _directory_offices(company):
    """Offices on one company card — occupied, reserved, and historical links."""
    spaces = company.spaces.select_related("floor").order_by("floor__code", "code")
    offices = []
    for space in spaces:
        status = getattr(space, "register_status", None) or ""
        floor = getattr(space, "floor", None)
        kind = _directory_office_kind(status)
        offices.append(
            {
                "code": space.code,
                "label": getattr(space, "short_label", None) or space.code,
                "floor": str(floor) if floor else "—",
                "status": status or "—",
                "kind": kind,
            }
        )
    return offices


def _normalize_directory_query(raw: str) -> str:
    return " ".join((raw or "").casefold().split())


def _company_ids_matching_office_query(q: str) -> set[int]:
    """Match internal code, floor, and canonical short_label (display office label)."""
    from apps.property.models import Space

    qn = _normalize_directory_query(q)
    if not qn:
        return set()
    ids: set[int] = set()
    compact_q = qn.replace(" ", "")
    for space in Space.objects.filter(resident_id__isnull=False).select_related("floor"):
        label = (getattr(space, "short_label", None) or space.code or "").casefold()
        code = (space.code or "").casefold()
        floor_code = (space.floor.code if space.floor_id else "").casefold()
        floor_name = (space.floor.name if space.floor_id else "").casefold()
        haystacks = (
            label,
            label.replace(" ", ""),
            code,
            floor_code,
            floor_name,
            f"{floor_code} {label}",
        )
        if any(qn in h or compact_q in h.replace(" ", "") for h in haystacks if h):
            ids.add(int(space.resident_id))
    return ids


class ResidentDirectoryListView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    """Read-only Rezident şirkətlər directory for Supply operators."""

    template_name = "erp/resident_directory.html"
    permission_required = ("resident.directory.view", "resident.view")
    permission_denied_message = "Rezident kataloquna baxış icazəniz yoxdur."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not user_can_view_resident_directory(request.user):
            raise PermissionDenied(self.permission_denied_message)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from django.core.paginator import Paginator

        from apps.core.search import filter_text_search

        ctx = super().get_context_data(**kwargs)
        q = (self.request.GET.get("q") or "").strip()
        base = ResidentCompany.objects.filter(is_internal=False, is_archived=False)
        qs = base.prefetch_related("spaces__floor").order_by("name")
        if q:
            name_qs = filter_text_search(
                qs,
                q,
                "name",
                "slug",
                "contact_person_name",
                "phone",
                "contact_email",
                "manager_name",
            )
            space_match = base.filter(
                Q(spaces__code__icontains=q)
                | Q(spaces__floor__name__icontains=q)
                | Q(spaces__floor__code__icontains=q)
            )
            office_ids = _company_ids_matching_office_query(q)
            office_qs = base.filter(pk__in=office_ids) if office_ids else base.none()
            qs = (name_qs | space_match | office_qs).distinct().order_by("name")

        try:
            page_num = max(1, int(self.request.GET.get("page") or 1))
        except (TypeError, ValueError):
            page_num = 1
        page = Paginator(qs, 50).get_page(page_num)
        cards = []
        for company in page.object_list:
            cards.append(
                {
                    "company": company,
                    "offices": _directory_offices(company),
                    "contact_name": company.contact_person_name or company.manager_name,
                    "contact_position": company.contact_person_position
                    or company.manager_position,
                    "contact_phone": company.contact_person_phone
                    or company.manager_phone
                    or company.phone,
                    "contact_email": company.contact_person_email
                    or company.manager_email
                    or company.contact_email,
                }
            )
        ctx.update(
            {
                "q": q,
                "cards": cards,
                "directory_mode": True,
                "page_obj": page,
                "company_total": page.paginator.count,
            }
        )
        return ctx


class ResidentDirectoryDetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/resident_directory_detail.html"
    permission_required = ("resident.directory.view", "resident.view")
    permission_denied_message = "Rezident kataloquna baxış icazəniz yoxdur."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not user_can_view_resident_directory(request.user):
            raise PermissionDenied(self.permission_denied_message)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from apps.maintenance.models import WorkOrderStatus
        from apps.tickets.models import CLOSED_STATUSES, OPEN_STATUSES

        ctx = super().get_context_data(**kwargs)
        company = _company(self.kwargs["slug"])
        ticket_qs = tickets_visible_to(self.request.user).filter(company=company)
        open_tickets = ticket_qs.filter(status__in=OPEN_STATUSES).order_by("-updated_at")
        ticket_history = ticket_qs.filter(status__in=CLOSED_STATUSES).order_by("-updated_at")
        wo_qs = work_orders_queryset_for(self.request.user).filter(
            Q(ticket__company=company) | Q(space__resident=company)
        )
        open_wo = wo_qs.filter(
            status__in=(
                WorkOrderStatus.OPEN,
                WorkOrderStatus.ASSIGNED,
                WorkOrderStatus.IN_PROGRESS,
            )
        ).order_by("-created_at")
        wo_history = wo_qs.exclude(
            status__in=(
                WorkOrderStatus.OPEN,
                WorkOrderStatus.ASSIGNED,
                WorkOrderStatus.IN_PROGRESS,
            )
        ).order_by("-created_at")
        preview = 10
        ctx.update(
            {
                "company": company,
                "offices": _directory_offices(company),
                "contact_name": company.contact_person_name or company.manager_name,
                "contact_position": company.contact_person_position
                or company.manager_position,
                "contact_phone": company.contact_person_phone
                or company.manager_phone
                or company.phone,
                "contact_email": company.contact_person_email
                or company.manager_email
                or company.contact_email,
                "open_tickets": list(open_tickets[:preview]),
                "ticket_history": list(ticket_history[:preview]),
                "open_work_orders": list(open_wo[:preview]),
                "work_order_history": list(wo_history[:preview]),
                "open_ticket_total": open_tickets.count(),
                "open_wo_total": open_wo.count(),
                "tickets_see_all_url": reverse("erp:tickets")
                + f"?company={company.pk}&tab=open",
                "work_orders_see_all_url": reverse("erp:work_orders") + "?status=open",
                # Legacy keys for older templates
                "tickets": list(open_tickets[:preview]),
                "work_orders": list(open_wo[:preview]),
                "hide_legal_fields": True,
                "directory_mode": True,
            }
        )
        return ctx


class ResidentCreateView(PermissionRequiredMixin, RoleRequiredMixin, CreateView):
    template_name = "erp/resident_form.html"
    form_class = ResidentCompanyForm
    model = ResidentCompany
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)
    permission_required = "resident.edit"
    permission_denied_message = "Rezident idarəetməsi icazəniz yoxdur."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["section"] = None
        return kwargs

    def form_valid(self, form):
        company = form.save(commit=False)
        try:
            save_resident_company(company, actor=self.request.user, create=True)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Rezident yaradıldı."))
        return redirect("erp:resident_detail", slug=company.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = _("Yeni rezident")
        ctx["section"] = None
        return ctx


class ResidentUpdateView(PermissionRequiredMixin, RoleRequiredMixin, UpdateView):
    template_name = "erp/resident_form.html"
    form_class = ResidentCompanyForm
    model = ResidentCompany
    slug_field = "slug"
    slug_url_kwarg = "slug"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)
    permission_required = "resident.edit"
    permission_denied_message = "Rezident idarəetməsi icazəniz yoxdur."

    def get_queryset(self):
        return ResidentCompany.objects.filter(is_internal=False)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        section = self.request.GET.get("section") or self.request.POST.get("section")
        kwargs["section"] = section if section in RESIDENT_FORM_SECTIONS else None
        return kwargs

    def form_valid(self, form):
        from django.urls import reverse

        company = form.save(commit=False)
        try:
            save_resident_company(company, actor=self.request.user, create=False)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Profil yeniləndi."))
        section = form.section or SECTION_GENERAL
        url = reverse("erp:resident_detail", kwargs={"slug": company.slug})
        return redirect(f"{url}?section={section}")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        section = self.request.GET.get("section")
        titles = {
            SECTION_GENERAL: _("Ümumi məlumatlar"),
            SECTION_CONTACTS: _("Əlaqəli şəxslər"),
            SECTION_BANK: _("Bank rekvizitləri"),
        }
        ctx["page_title"] = titles.get(section, _("Rezidenti redaktə et"))
        ctx["company"] = self.object
        ctx["section"] = section if section in RESIDENT_FORM_SECTIONS else None
        return ctx


class ResidentArchiveView(PermissionRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)
    permission_required = "resident.edit"
    permission_denied_message = "Rezident idarəetməsi icazəniz yoxdur."

    def post(self, request, slug):
        company = _company(slug)
        archive_resident_company(company, actor=request.user)
        messages.success(request, _("Şirkət arxivləndi. Portal bağlandı."))
        return redirect("erp:resident_detail", slug=company.slug)


class ResidentUnarchiveView(PermissionRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)
    permission_required = "resident.edit"
    permission_denied_message = "Rezident idarəetməsi icazəniz yoxdur."

    def post(self, request, slug):
        company = _company(slug)
        unarchive_resident_company(company, actor=request.user)
        messages.success(
            request,
            _("Şirkət arxivdən çıxarıldı. Portal ayrıca aktivləşdirilməlidir."),
        )
        return redirect("erp:resident_detail", slug=company.slug)


class ResidentDocumentsView(StaffRequiredMixin, TemplateView):
    template_name = "erp/resident_documents.html"

    def dispatch(self, request, *args, **kwargs):
        if user_is_reception_limited(request.user):
            raise PermissionDenied(_("Resepsiya sənədlərə baxa bilməz."))
        if not user_can_view_resident_legal_docs(request.user):
            raise PermissionDenied(_("Sənədlərə giriş icazəniz yoxdur."))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = _company(self.kwargs["slug"])
        type_filter = (self.request.GET.get("type") or "").strip()
        docs = (
            Document.objects.filter(company=company)
            .select_related("document_type", "parent_document", "lease")
            .order_by("-document_date", "-id")
        )
        if type_filter:
            docs = docs.filter(document_type__code=type_filter)
        # Ensure seeded types exist for slot UI
        for code, name in SEED_DOCUMENT_TYPES:
            DocumentType.objects.get_or_create(code=code, defaults={"name": name})
        types = list(DocumentType.objects.filter(code__in=[c for c, _ in SEED_DOCUMENT_TYPES]).order_by("name"))
        by_type = {t.code: [] for t in types}
        by_type[""] = []
        for d in Document.objects.filter(company=company).select_related("document_type"):
            code = d.document_type.code if d.document_type_id else ""
            by_type.setdefault(code, []).append(d)
        slots = []
        for t in types:
            slots.append({"type": t, "docs": by_type.get(t.code, [])})
        untitled = by_type.get("", [])
        ctx.update(
            {
                "company": company,
                "documents": docs,
                "document_slots": slots,
                "untitled_docs": untitled,
                "type_filter": type_filter,
                "can_manage": user_can_manage_resident_profile(self.request.user),
                "section": SECTION_DOCUMENTS,
                "can_view_legal": True,
                "can_manage_resident": user_can_manage_resident_profile(self.request.user),
            }
        )
        return ctx


class ResidentDocumentCreateView(PermissionRequiredMixin, RoleRequiredMixin, FormView):
    template_name = "erp/resident_document_form.html"
    form_class = ResidentDocumentForm
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)
    permission_required = "resident.edit"
    permission_denied_message = "Rezident idarəetməsi icazəniz yoxdur."

    def dispatch(self, request, *args, **kwargs):
        self.company = _company(kwargs["slug"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.company
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        type_code = self.request.GET.get("type")
        if type_code:
            dt = DocumentType.objects.filter(code=type_code).first()
            if dt:
                initial["document_type"] = dt.pk
        return initial

    def form_valid(self, form):
        try:
            DocumentService.upload_new(
                title=form.cleaned_data["title"],
                uploaded_file=form.cleaned_data["file"],
                company=self.company,
                document_type=form.cleaned_data.get("document_type"),
                document_date=form.cleaned_data.get("document_date"),
                visible_to_resident=bool(form.cleaned_data.get("visible_to_resident")),
                parent_document=form.cleaned_data.get("parent_document"),
                lease=form.cleaned_data.get("lease"),
                created_by=self.request.user,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Sənəd əlavə olundu."))
        return redirect("erp:resident_documents", slug=self.company.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["company"] = self.company
        ctx["page_title"] = _("Yeni sənəd")
        ctx["section"] = SECTION_DOCUMENTS
        return ctx


class ResidentDocumentUpdateView(PermissionRequiredMixin, RoleRequiredMixin, FormView):
    template_name = "erp/resident_document_form.html"
    form_class = ResidentDocumentForm
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)
    permission_required = "resident.edit"
    permission_denied_message = "Rezident idarəetməsi icazəniz yoxdur."

    def dispatch(self, request, *args, **kwargs):
        self.company = _company(kwargs["slug"])
        self.document = get_object_or_404(Document, pk=kwargs["pk"], company=self.company)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.company
        kwargs["instance"] = self.document
        return kwargs

    def form_valid(self, form):
        try:
            DocumentService.update_meta(
                self.document,
                title=form.cleaned_data["title"],
                document_type=form.cleaned_data.get("document_type"),
                document_date=form.cleaned_data.get("document_date"),
                visible_to_resident=bool(form.cleaned_data.get("visible_to_resident")),
                lease=form.cleaned_data.get("lease"),
                parent_document=form.cleaned_data.get("parent_document"),
                actor=self.request.user,
            )
            uploaded = form.cleaned_data.get("file")
            if uploaded:
                DocumentService.add_version(
                    self.document,
                    uploaded_file=uploaded,
                    created_by=self.request.user,
                )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, _("Sənəd yeniləndi."))
        return redirect("erp:resident_documents", slug=self.company.slug)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["company"] = self.company
        ctx["document"] = self.document
        ctx["page_title"] = _("Sənədi redaktə et")
        ctx["section"] = SECTION_DOCUMENTS
        return ctx


class ResidentDocumentDeleteView(PermissionRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT)
    permission_required = "resident.edit"
    permission_denied_message = "Rezident idarəetməsi icazəniz yoxdur."

    def post(self, request, slug, pk):
        company = _company(slug)
        document = get_object_or_404(Document, pk=pk, company=company)
        try:
            DocumentService.delete_document(document, actor=request.user)
            messages.success(request, _("Sənəd silindi."))
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("erp:resident_documents", slug=company.slug)


class ResidentDocumentDownloadView(StaffRequiredMixin, View):
    def get(self, request, slug, pk):
        from apps.documents.access import user_can_download_document

        company = _company(slug)
        if user_is_reception_limited(request.user) or not user_can_view_resident_legal_docs(request.user):
            raise PermissionDenied(_("Sənəd endirmə icazəniz yoxdur."))
        document = get_object_or_404(Document, pk=pk, company=company)
        if not user_can_download_document(request.user, document):
            raise PermissionDenied(_("Bu sənədin məxfilik səviyyəsinə görə endirmə icazəniz yoxdur."))
        if not document.file:
            raise Http404()
        inline = request.GET.get("inline") == "1"
        try:
            f = document.file.open("rb")
        except Exception as exc:
            raise Http404() from exc
        content_type = (
            document.content_type
            or mimetypes.guess_type(document.file.name)[0]
            or "application/octet-stream"
        )
        return FileResponse(
            f,
            as_attachment=not inline,
            filename=document.file.name.rsplit("/", 1)[-1],
            content_type=content_type,
        )


def enrich_resident_detail_context(request, company, ctx: dict) -> dict:
    """Extend ResidentDetailView with 6-section hub / lease card / reception limits."""
    reception = user_is_reception_limited(request.user)
    can_legal = user_can_view_resident_legal_docs(request.user) and not reception
    can_manage = user_can_manage_resident_profile(request.user)
    section = (request.GET.get("section") or SECTION_HUB).strip()
    if section not in {
        SECTION_HUB,
        SECTION_GENERAL,
        SECTION_CONTACTS,
        SECTION_BANK,
        SECTION_LEASES,
        SECTION_ACCESS,
    }:
        section = SECTION_HUB
    if reception and section in LEGAL_SECTIONS - {SECTION_ACCESS}:
        # Reception may only see hub + access-ish guest summary on hub
        if section != SECTION_HUB:
            section = SECTION_HUB

    summary = lease_date_summary(company) if can_legal else None
    lease_rows = lease_display_rows(company) if can_legal and section == SECTION_LEASES else []
    parking = parking_for_company(company)

    ctx.update(
        {
            "section": section,
            "tab": section,
            "can_view_legal": can_legal,
            "can_manage_resident": can_manage,
            "reception_limited": reception,
            "lease_summary": summary,
            "lease_rows": lease_rows,
            "parking_assignments": parking,
            "display_address": company.display_address if can_legal else "",
            "hide_legal_fields": reception or not can_legal,
        }
    )
    return ctx
