"""Security floor plan / device portal views."""

from __future__ import annotations

import mimetypes

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView, View

from apps.accounts.mixins import SecurityPortalMixin
from apps.core.search import filter_text_search
from apps.core.services import DomainError
from apps.security.access import can_edit_security_plans, can_view_security_plans
from apps.security.forms import DeviceForm, PlanUploadForm, RevisionUploadForm
from apps.security.models import (
    ConversionStatus,
    SecurityDevice,
    SecurityDevicePin,
    SecurityFloorPlan,
    SecurityFloorPlanRevision,
)
from apps.security.services import (
    SecurityDeviceService,
    SecurityPinService,
    SecurityPlanService,
    log_download,
)


class PlanAccessMixin(SecurityPortalMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_view_security_plans(request.user):
            raise PermissionDenied(_("Planlara baxış icazəniz yoxdur."))
        return super().dispatch(request, *args, **kwargs)


class PlanEditRequiredMixin:
    """Use inside dispatch after PlanAccessMixin — raises if cannot edit."""

    def require_edit(self, request):
        if not can_edit_security_plans(request.user):
            raise PermissionDenied(_("Bu əməliyyat üçün icazəniz yoxdur."))


class PlanListView(PlanAccessMixin, TemplateView):
    template_name = "security/plans.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        plans = (
            SecurityFloorPlan.objects.filter(is_active=True)
            .select_related("floor", "floor__building")
            .prefetch_related(
                Prefetch(
                    "revisions",
                    queryset=SecurityFloorPlanRevision.objects.order_by("-revision_number"),
                )
            )
        )
        rows = []
        for p in plans:
            active = next((r for r in p.revisions.all() if r.is_active), None)
            latest = p.revisions.all()[0] if p.revisions.all() else None
            rows.append({"plan": p, "active": active, "latest": latest})
        ctx["rows"] = rows
        ctx["can_edit"] = can_edit_security_plans(self.request.user)
        ctx["upload_form"] = PlanUploadForm() if ctx["can_edit"] else None
        return ctx


class PlanUploadView(PlanAccessMixin, PlanEditRequiredMixin, View):
    def post(self, request):
        self.require_edit(request)
        form = PlanUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, _("Yükləmə uğursuz: form xətaları."))
            return redirect("security:plans")
        try:
            plan, _rev = SecurityPlanService.create_plan_with_upload(
                user=request.user,
                title=form.cleaned_data["title"],
                floor=form.cleaned_data["floor"],
                category=form.cleaned_data["category"],
                uploaded=form.cleaned_data["source_file"],
                request=request,
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect("security:plans")
        messages.success(
            request,
            _("Plan yükləndi. Conversion worker SVG hazırlayana qədər gözləyin."),
        )
        return redirect("security:plan_detail", pk=plan.pk)


class PlanDetailView(PlanAccessMixin, TemplateView):
    template_name = "security/plan_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        plan = get_object_or_404(
            SecurityFloorPlan.objects.select_related("floor", "floor__building"),
            pk=self.kwargs["pk"],
        )
        revisions = list(plan.revisions.all())
        active = next((r for r in revisions if r.is_active), None)
        view_rev = active
        rev_id = self.request.GET.get("revision")
        if rev_id:
            view_rev = next((r for r in revisions if str(r.pk) == str(rev_id)), active)
        pins = []
        if view_rev and view_rev.is_active and view_rev.conversion_status == ConversionStatus.READY:
            pins = list(
                view_rev.pins.select_related("device").filter(device__is_active=True)
            )
        elif view_rev and can_edit_security_plans(self.request.user):
            # Editors may preview pins on non-active ready revisions.
            if view_rev.conversion_status == ConversionStatus.READY:
                pins = list(
                    view_rev.pins.select_related("device").filter(device__is_active=True)
                )
        can_edit = can_edit_security_plans(self.request.user)
        devices = []
        if can_edit and view_rev:
            from apps.security.forms import PinPlaceForm

            devices = list(PinPlaceForm(plan=plan).fields["device"].queryset)
        ctx.update(
            {
                "plan": plan,
                "revisions": revisions,
                "view_rev": view_rev,
                "active_rev": active,
                "pins": pins,
                "can_edit": can_edit,
                "devices": devices,
                "revision_form": RevisionUploadForm() if can_edit else None,
                "show_viewer": bool(
                    view_rev
                    and view_rev.conversion_status == ConversionStatus.READY
                    and view_rev.svg_file
                ),
            }
        )
        return ctx


class PlanRevisionUploadView(PlanAccessMixin, PlanEditRequiredMixin, View):
    def post(self, request, pk):
        self.require_edit(request)
        plan = get_object_or_404(SecurityFloorPlan, pk=pk)
        form = RevisionUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, _("Yükləmə uğursuz."))
            return redirect("security:plan_detail", pk=pk)
        try:
            SecurityPlanService.upload_revision(
                user=request.user,
                plan=plan,
                uploaded=form.cleaned_data["source_file"],
                request=request,
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect("security:plan_detail", pk=pk)
        messages.success(request, _("Yeni revision yükləndi (pending)."))
        return redirect("security:plan_detail", pk=pk)


class PlanRevisionActivateView(PlanAccessMixin, PlanEditRequiredMixin, View):
    def post(self, request, pk, revision_id):
        self.require_edit(request)
        revision = get_object_or_404(
            SecurityFloorPlanRevision, pk=revision_id, plan_id=pk
        )
        try:
            SecurityPlanService.activate_revision(
                user=request.user, revision=revision, request=request
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect("security:plan_detail", pk=pk)
        messages.success(request, _("Revision aktivləşdirildi."))
        return redirect("security:plan_detail", pk=pk)


class PlanRevisionRetryView(PlanAccessMixin, PlanEditRequiredMixin, View):
    def post(self, request, pk, revision_id):
        self.require_edit(request)
        revision = get_object_or_404(
            SecurityFloorPlanRevision, pk=revision_id, plan_id=pk
        )
        try:
            SecurityPlanService.retry_conversion(
                user=request.user, revision=revision, request=request
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect("security:plan_detail", pk=pk)
        messages.success(request, _("Conversion növbəyə alındı."))
        return redirect("security:plan_detail", pk=pk)


class PlanPinUpsertView(PlanAccessMixin, PlanEditRequiredMixin, View):
    def post(self, request, pk, revision_id):
        self.require_edit(request)
        revision = get_object_or_404(
            SecurityFloorPlanRevision, pk=revision_id, plan_id=pk
        )
        device_id = request.POST.get("device")
        device = get_object_or_404(SecurityDevice, pk=device_id)
        try:
            SecurityPinService.upsert_pin(
                user=request.user,
                revision=revision,
                device=device,
                x_pct=request.POST.get("x_pct"),
                y_pct=request.POST.get("y_pct"),
                note=request.POST.get("note") or "",
                request=request,
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect(
            reverse("security:plan_detail", kwargs={"pk": pk})
            + f"?revision={revision_id}"
        )


class PlanPinDeleteView(PlanAccessMixin, PlanEditRequiredMixin, View):
    def post(self, request, pk, revision_id, pin_id):
        self.require_edit(request)
        pin = get_object_or_404(
            SecurityDevicePin, pk=pin_id, revision_id=revision_id, revision__plan_id=pk
        )
        try:
            SecurityPinService.delete_pin(user=request.user, pin=pin, request=request)
            messages.success(request, _("Pin silindi."))
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect(
            reverse("security:plan_detail", kwargs={"pk": pk})
            + f"?revision={revision_id}"
        )


class PlanSvgView(PlanAccessMixin, View):
    def get(self, request, pk, revision_id):
        revision = get_object_or_404(
            SecurityFloorPlanRevision, pk=revision_id, plan_id=pk
        )
        if revision.conversion_status != ConversionStatus.READY or not revision.svg_file:
            raise Http404()
        # Non-editors only see active revision SVG.
        if not can_edit_security_plans(request.user) and not revision.is_active:
            raise PermissionDenied()
        f = revision.svg_file.open("rb")
        resp = FileResponse(f, content_type="image/svg+xml")
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        resp["Cache-Control"] = "private, no-store"
        return resp


class PlanSourceDownloadView(PlanAccessMixin, View):
    def get(self, request, pk, revision_id):
        revision = get_object_or_404(
            SecurityFloorPlanRevision, pk=revision_id, plan_id=pk
        )
        if not revision.source_file:
            raise Http404()
        if not can_edit_security_plans(request.user) and not revision.is_active:
            # Management may download active originals only.
            if not revision.is_active:
                raise PermissionDenied()
        log_download(user=request.user, revision=revision, kind="source", request=request)
        filename = revision.source_file.name.rsplit("/", 1)[-1]
        return FileResponse(
            revision.source_file.open("rb"),
            as_attachment=True,
            filename=filename,
            content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        )


class DeviceListView(PlanAccessMixin, TemplateView):
    template_name = "security/devices.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = (self.request.GET.get("q") or "").strip()
        qs = SecurityDevice.objects.all()
        dtype = self.request.GET.get("type") or ""
        if dtype:
            qs = qs.filter(device_type=dtype)
        active = self.request.GET.get("active")
        if active == "1":
            qs = qs.filter(is_active=True)
        elif active == "0":
            qs = qs.filter(is_active=False)
        if q:
            # Cast inet → text before SearchFold (avoids PostgreSQL inet COALESCE error).
            from django.db.models import CharField
            from django.db.models.functions import Cast

            qs = qs.annotate(_ip_txt=Cast("ip_address", CharField()))
            qs = filter_text_search(qs, q, "name", "location_note", "_ip_txt")
        ctx["devices"] = qs
        ctx["can_edit"] = can_edit_security_plans(self.request.user)
        ctx["form"] = DeviceForm() if ctx["can_edit"] else None
        ctx["q"] = q
        ctx["type"] = dtype
        ctx["active"] = active or ""
        return ctx


class DeviceCreateView(PlanAccessMixin, PlanEditRequiredMixin, View):
    def post(self, request):
        self.require_edit(request)
        form = DeviceForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Cihaz yaradılmadı."))
            return redirect("security:devices")
        try:
            SecurityDeviceService.create_device(
                user=request.user,
                name=form.cleaned_data["name"],
                device_type=form.cleaned_data["device_type"],
                ip_address=form.cleaned_data.get("ip_address"),
                location_note=form.cleaned_data.get("location_note") or "",
                request=request,
            )
        except DomainError as exc:
            messages.error(request, str(exc))
            return redirect("security:devices")
        messages.success(request, _("Cihaz yaradıldı."))
        return redirect("security:devices")


class DeviceUpdateView(PlanAccessMixin, PlanEditRequiredMixin, View):
    def post(self, request, pk):
        self.require_edit(request)
        device = get_object_or_404(SecurityDevice, pk=pk)
        form = DeviceForm(request.POST, instance=device)
        if not form.is_valid():
            messages.error(request, _("Yeniləmə uğursuz."))
            return redirect("security:devices")
        try:
            SecurityDeviceService.update_device(
                user=request.user,
                device=device,
                name=form.cleaned_data["name"],
                device_type=form.cleaned_data["device_type"],
                ip_address=form.cleaned_data.get("ip_address"),
                location_note=form.cleaned_data.get("location_note") or "",
                is_active=form.cleaned_data.get("is_active", True),
            )
        except DomainError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Cihaz yeniləndi."))
        return redirect("security:devices")


class DeviceDeactivateView(PlanAccessMixin, PlanEditRequiredMixin, View):
    def post(self, request, pk):
        self.require_edit(request)
        device = get_object_or_404(SecurityDevice, pk=pk)
        try:
            SecurityDeviceService.deactivate_device(
                user=request.user, device=device, request=request
            )
            messages.success(request, _("Cihaz deaktiv edildi."))
        except DomainError as exc:
            messages.error(request, str(exc))
        return redirect("security:devices")
