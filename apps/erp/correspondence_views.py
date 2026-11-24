"""ERP kargüzarlıq / correspondence registry (Phase 10)."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.mixins import PermissionRequiredMixin, StaffRequiredMixin
from apps.core.services import DomainError
from apps.documents.access import user_can_download_document
from apps.documents.correspondence import (
    correspondence_queryset,
    filter_correspondence,
    prepare_outgoing_reply,
    record_dispatch,
    register_incoming_letter,
    route_correspondence,
    _approved_version_for,
)
from apps.documents.models import (
    CorrespondenceDirection,
    CorrespondenceStatus,
    Document,
    DocumentDispatch,
)
from apps.documents.services import DocumentService
from apps.rbac.services import require_permission, user_has_permission
from apps.residents.models import ResidentCompany
from apps.tickets.models import TicketDepartment


def _parse_date(raw: str):
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise DomainError(_("Tarix formatı yanlışdır (YYYY-MM-DD)."))


class CorrespondenceListView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/correspondence_list.html"
    permission_required = "document.view"
    permission_denied_message = "Sənədlərə baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        request = self.request
        qs = correspondence_queryset().order_by("-received_at", "-id")
        filters = {
            "registry": request.GET.get("registry") or "",
            "external_ref": request.GET.get("external_ref") or "",
            "company_id": request.GET.get("company") or "",
            "direction": request.GET.get("direction") or "",
            "date_from": request.GET.get("date_from") or "",
            "date_to": request.GET.get("date_to") or "",
            "date_field": request.GET.get("date_field") or "received",
            "department_id": request.GET.get("department") or "",
            "status": request.GET.get("status") or "",
        }
        qs = filter_correspondence(qs, **filters)[:200]
        ctx.update(
            {
                "rows": qs,
                "filters": filters,
                "companies": ResidentCompany.objects.filter(status="active").order_by("name")[:300],
                "departments": TicketDepartment.objects.order_by("name"),
                "status_choices": CorrespondenceStatus.choices,
                "can_edit": user_has_permission(request.user, "document.edit"),
                "submit_token": uuid.uuid4().hex,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        require_permission(request.user, "document.edit", message=_("Qeydiyyat icazəniz yoxdur."))
        action = request.POST.get("action")
        token = (request.POST.get("submit_token") or "").strip()
        session_key = f"corr_list_{action}"
        if token and request.session.get(session_key) == token:
            messages.info(request, _("Bu forma artıq göndərilib."))
            return redirect("erp:correspondence_list")
        try:
            if action == "register_incoming":
                company = None
                cid = request.POST.get("company_id")
                if cid:
                    company = get_object_or_404(ResidentCompany, pk=cid)
                lease = None
                lid = request.POST.get("lease_id")
                if lid:
                    from apps.leases.models import Lease

                    lease = get_object_or_404(Lease, pk=lid)
                dept = None
                did = request.POST.get("department_id")
                if did:
                    dept = get_object_or_404(TicketDepartment, pk=did)
                uploaded = request.FILES.get("file")
                if not uploaded:
                    raise DomainError(_("Əsas fayl tələb olunur."))
                doc = register_incoming_letter(
                    title=request.POST.get("title") or "",
                    uploaded_file=uploaded,
                    actor=request.user,
                    company=company,
                    lease=lease,
                    letter_date=_parse_date(request.POST.get("letter_date") or ""),
                    received_at=_parse_date(request.POST.get("received_at") or ""),
                    external_reference=request.POST.get("external_reference") or "",
                    routed_department=dept,
                )
                if token:
                    request.session[session_key] = token
                    request.session.modified = True
                messages.success(
                    request,
                    _("Qeydiyyat: %(num)s") % {"num": doc.registry_number},
                )
                return redirect("erp:correspondence_detail", pk=doc.pk)
            messages.error(request, _("Naməlum əməliyyat."))
        except (DomainError, ValidationError) as exc:
            messages.error(request, str(exc))
        return redirect("erp:correspondence_list")


class CorrespondenceDetailView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/correspondence_detail.html"
    permission_required = "document.view"
    permission_denied_message = "Sənədlərə baxış icazəniz yoxdur."

    def get_document(self):
        return get_object_or_404(
            correspondence_queryset().prefetch_related("versions", "dispatches"),
            pk=self.kwargs["pk"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        doc = self.get_document()
        if not user_can_download_document(self.request.user, doc):
            # Still allow meta view for staff with document.view; download gated separately.
            pass
        approved = _approved_version_for(doc)
        dispatch = doc.dispatches.order_by("-dispatched_at").first()
        linked = doc.related_correspondence
        ctx.update(
            {
                "doc": doc,
                "versions": doc.versions.all(),
                "approved_version": approved,
                "latest_dispatch": dispatch,
                "linked": linked,
                "approval_info": DocumentService.approval_summary_for_document(doc),
                "departments": TicketDepartment.objects.order_by("name"),
                "can_edit": user_has_permission(self.request.user, "document.edit"),
                "can_download": user_can_download_document(self.request.user, doc),
                "submit_token": uuid.uuid4().hex,
                "CorrespondenceDirection": CorrespondenceDirection,
                "CorrespondenceStatus": CorrespondenceStatus,
            }
        )
        return ctx

    def post(self, request, *args, **kwargs):
        doc = self.get_document()
        require_permission(request.user, "document.edit", message=_("Əməliyyat icazəniz yoxdur."))
        action = request.POST.get("action")
        token = (request.POST.get("submit_token") or "").strip()
        session_key = f"corr_{doc.pk}_{action}"
        if token and request.session.get(session_key) == token:
            messages.info(request, _("Bu forma artıq göndərilib."))
            return redirect("erp:correspondence_detail", pk=doc.pk)
        try:
            if action == "route":
                dept = get_object_or_404(TicketDepartment, pk=request.POST.get("department_id"))
                route_correspondence(document=doc, department=dept, actor=request.user)
                messages.success(request, _("Yönləndirildi."))
            elif action == "prepare_reply":
                uploaded = request.FILES.get("file")
                if not uploaded:
                    raise DomainError(_("Cavab faylı tələb olunur."))
                reply = prepare_outgoing_reply(
                    incoming=doc,
                    title=request.POST.get("title") or f"Cavab: {doc.registry_number}",
                    uploaded_file=uploaded,
                    actor=request.user,
                )
                if token:
                    request.session[session_key] = token
                    request.session.modified = True
                messages.success(request, _("Cavab: %(num)s") % {"num": reply.registry_number})
                return redirect("erp:correspondence_detail", pk=reply.pk)
            elif action == "add_version":
                uploaded = request.FILES.get("file")
                if not uploaded:
                    raise DomainError(_("Fayl tələb olunur."))
                DocumentService.add_version(doc, uploaded_file=uploaded, created_by=request.user)
                messages.success(request, _("Yeni versiya əlavə olundu."))
            elif action == "submit_approval":
                DocumentService.submit_for_approval(doc, actor=request.user)
                doc.correspondence_status = CorrespondenceStatus.PENDING_APPROVAL
                doc.save(update_fields=["correspondence_status", "updated_at"])
                messages.success(request, _("Təsdiqə göndərildi."))
            elif action == "dispatch":
                record_dispatch(
                    document=doc,
                    actor=request.user,
                    recipient=request.POST.get("recipient") or "",
                    channel=request.POST.get("channel") or "manual",
                    notes=request.POST.get("notes") or "",
                    operation_key=request.POST.get("operation_key") or "",
                )
                messages.success(request, _("Göndərmə qeyd olundu."))
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except PermissionDenied:
            raise
        except (DomainError, ValidationError) as exc:
            messages.error(request, str(exc))
            return redirect("erp:correspondence_detail", pk=doc.pk)
        if token:
            request.session[session_key] = token
            request.session.modified = True
        return redirect("erp:correspondence_detail", pk=doc.pk)
