"""Resident company profile + documents CRUD (ERP)."""

from __future__ import annotations

import mimetypes

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, FormView, TemplateView, UpdateView

from apps.accounts.mixins import RoleRequiredMixin, StaffRequiredMixin
from apps.accounts.models import Role
from apps.documents.models import SEED_DOCUMENT_TYPES, Document, DocumentType
from apps.documents.services import DocumentService
from apps.erp.forms import RESIDENT_FORM_SECTIONS, ResidentCompanyForm, ResidentDocumentForm
from apps.residents.company_sync import (
    archive_resident_company,
    save_resident_company,
    unarchive_resident_company,
)
from apps.residents.lease_dates import lease_date_summary, lease_display_rows, parking_for_company
from apps.residents.models import ResidentCompany
from apps.residents.permissions import (
    user_can_manage_resident_profile,
    user_can_view_resident_legal_docs,
    user_is_reception_limited,
)

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


class ResidentCreateView(RoleRequiredMixin, CreateView):
    template_name = "erp/resident_form.html"
    form_class = ResidentCompanyForm
    model = ResidentCompany
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM)

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


class ResidentUpdateView(RoleRequiredMixin, UpdateView):
    template_name = "erp/resident_form.html"
    form_class = ResidentCompanyForm
    model = ResidentCompany
    slug_field = "slug"
    slug_url_kwarg = "slug"
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM)

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


class ResidentArchiveView(RoleRequiredMixin, View):
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM)

    def post(self, request, slug):
        company = _company(slug)
        archive_resident_company(company, actor=request.user)
        messages.success(request, _("Şirkət arxivləndi. Portal bağlandı."))
        return redirect("erp:resident_detail", slug=company.slug)


class ResidentUnarchiveView(RoleRequiredMixin, View):
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM)

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


class ResidentDocumentCreateView(RoleRequiredMixin, FormView):
    template_name = "erp/resident_document_form.html"
    form_class = ResidentDocumentForm
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM)

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


class ResidentDocumentUpdateView(RoleRequiredMixin, FormView):
    template_name = "erp/resident_document_form.html"
    form_class = ResidentDocumentForm
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM)

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


class ResidentDocumentDeleteView(RoleRequiredMixin, View):
    allowed_roles = (Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM)

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
        company = _company(slug)
        if user_is_reception_limited(request.user) or not user_can_view_resident_legal_docs(request.user):
            raise PermissionDenied(_("Sənəd endirmə icazəniz yoxdur."))
        document = get_object_or_404(Document, pk=pk, company=company)
        if not document.file:
            raise Http404()
        inline = request.GET.get("inline") == "1"
        try:
            f = document.file.open("rb")
        except Exception as exc:
            raise Http404() from exc
        content_type = mimetypes.guess_type(document.file.name)[0] or "application/octet-stream"
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
