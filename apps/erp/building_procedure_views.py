"""ERP CRUD for building internal procedure files (resident portal)."""

from __future__ import annotations

import mimetypes

from django.contrib import messages
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from apps.accounts.mixins import RoleRequiredMixin
from apps.accounts.models import Role
from apps.comms.models import BuildingProcedure
from apps.erp.forms import BuildingProcedureForm

_ALLOWED = (Role.ADMIN, Role.MANAGEMENT, Role.PROPERTY_FM)


class BuildingProcedureListView(RoleRequiredMixin, ListView):
    template_name = "erp/building_procedures.html"
    context_object_name = "procedures"
    allowed_roles = _ALLOWED
    queryset = BuildingProcedure.objects.all()


class BuildingProcedureCreateView(RoleRequiredMixin, CreateView):
    template_name = "erp/building_procedure_form.html"
    form_class = BuildingProcedureForm
    model = BuildingProcedure
    allowed_roles = _ALLOWED
    success_url = reverse_lazy("erp:building_procedures")

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.created_by = self.request.user
        if obj.is_published and not obj.published_at:
            obj.published_at = timezone.localdate()
        obj.save()
        messages.success(self.request, _("Daxili prosedur əlavə olundu."))
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = _("Yeni daxili prosedur")
        return ctx


class BuildingProcedureUpdateView(RoleRequiredMixin, UpdateView):
    template_name = "erp/building_procedure_form.html"
    form_class = BuildingProcedureForm
    model = BuildingProcedure
    allowed_roles = _ALLOWED
    success_url = reverse_lazy("erp:building_procedures")
    pk_url_kwarg = "pk"

    def form_valid(self, form):
        obj = form.save(commit=False)
        if obj.is_published and not obj.published_at:
            obj.published_at = timezone.localdate()
        obj.save()
        messages.success(self.request, _("Daxili prosedur yeniləndi."))
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = _("Daxili proseduru redaktə et")
        ctx["procedure"] = self.object
        return ctx


class BuildingProcedureDeleteView(RoleRequiredMixin, View):
    allowed_roles = _ALLOWED

    def post(self, request, pk):
        procedure = get_object_or_404(BuildingProcedure, pk=pk)
        name = procedure.file.name if procedure.file else ""
        storage = procedure.file.storage if procedure.file else None
        with transaction.atomic():
            procedure.delete()

            def _cleanup():
                if name and storage:
                    try:
                        storage.delete(name)
                    except Exception:
                        pass

            transaction.on_commit(_cleanup)
        messages.success(request, _("Daxili prosedur silindi."))
        return redirect("erp:building_procedures")


class BuildingProcedureDownloadView(RoleRequiredMixin, View):
    allowed_roles = _ALLOWED

    def get(self, request, pk):
        procedure = get_object_or_404(BuildingProcedure, pk=pk)
        if not procedure.file:
            raise Http404()
        filename = procedure.display_filename
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        inline = request.GET.get("inline") == "1"
        return FileResponse(
            procedure.file.open("rb"),
            as_attachment=not inline,
            filename=filename,
            content_type=content_type,
        )
