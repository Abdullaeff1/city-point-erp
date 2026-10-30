"""ERP space drawing upload / download / SVG / access queue (Admin + Property/FM)."""

from __future__ import annotations

import mimetypes

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.mixins import RoleRequiredMixin
from apps.accounts.models import Role
from apps.property.drawings import (
    create_space_drawing,
    decide_access_request,
    user_can_manage_space_drawings,
    user_may_download_drawing,
)
from apps.property.models import (
    Space,
    SpaceDrawing,
    SpaceDrawingAccessRequest,
    SpaceDrawingAccessStatus,
    SpaceDrawingKind,
)


class DrawingManagerMixin(RoleRequiredMixin):
    """Only Admin + Property/FM (explicitly excludes Management-only for drawing ops)."""

    allowed_roles = (Role.PROPERTY_FM,)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not user_can_manage_space_drawings(request.user):
            raise PermissionDenied(_("Sahə rəsmləri yalnız Admin və Property/FM üçündür."))
        # Skip RoleRequiredMixin's ADMIN|MANAGEMENT|*allowed — we already gated.
        from django.contrib.auth.mixins import LoginRequiredMixin

        return LoginRequiredMixin.dispatch(self, request, *args, **kwargs)


def _tab_for_kind(kind: str) -> str:
    if kind == SpaceDrawingKind.TECHNICAL_PLAN:
        return "technical_plan"
    return "dwg"


class SpaceDrawingUploadView(DrawingManagerMixin, View):
    def post(self, request, code):
        space = get_object_or_404(Space, code=code)
        kind = (request.POST.get("kind") or "").strip()
        uploaded = request.FILES.get("file")
        tab = _tab_for_kind(kind)
        if not uploaded:
            messages.error(request, _("Fayl seçin."))
            return redirect(f"{reverse('erp:space_detail', kwargs={'code': space.code})}?tab={tab}")
        try:
            create_space_drawing(
                space=space,
                uploaded_file=uploaded,
                kind=kind or None,
                uploaded_by=request.user,
            )
            messages.success(request, _("Fayl yükləndi."))
        except Exception as exc:  # noqa: BLE001
            messages.error(request, str(exc))
        return redirect(f"{reverse('erp:space_detail', kwargs={'code': space.code})}?tab={tab}")


class SpaceDrawingDownloadView(View):
    """Staff managers always; residents only with approved unexpired request (portal URL separate)."""

    def get(self, request, pk):
        if not request.user.is_authenticated:
            raise PermissionDenied
        drawing = get_object_or_404(SpaceDrawing.objects.select_related("space"), pk=pk)
        if not user_may_download_drawing(request.user, drawing):
            raise PermissionDenied(_("Bu faylı yükləmək icazəniz yoxdur."))
        if not drawing.file:
            raise Http404()
        filename = drawing.original_name or drawing.file.name.rsplit("/", 1)[-1]
        content_type = drawing.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return FileResponse(
            drawing.file.open("rb"),
            as_attachment=True,
            filename=filename,
            content_type=content_type,
        )


class SpaceDrawingSvgView(DrawingManagerMixin, View):
    def get(self, request, pk):
        drawing = get_object_or_404(SpaceDrawing, pk=pk)
        if not drawing.svg_file:
            raise Http404()
        f = drawing.svg_file.open("rb")
        resp = FileResponse(f, content_type="image/svg+xml")
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        resp["Cache-Control"] = "private, no-store"
        return resp


class SpaceDrawingPngPreviewView(DrawingManagerMixin, View):
    def get(self, request, pk):
        drawing = get_object_or_404(SpaceDrawing, pk=pk)
        if drawing.kind != SpaceDrawingKind.TECHNICAL_PLAN or not drawing.is_png or not drawing.file:
            raise Http404()
        resp = FileResponse(drawing.file.open("rb"), content_type="image/png")
        resp["Cache-Control"] = "private, no-store"
        return resp


class DrawingAccessQueueView(DrawingManagerMixin, TemplateView):
    template_name = "erp/drawing_access_queue.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["pending"] = (
            SpaceDrawingAccessRequest.objects.filter(status=SpaceDrawingAccessStatus.PENDING)
            .select_related("user", "drawing", "drawing__space")
            .order_by("created_at")
        )
        return ctx


class DrawingAccessDecideView(DrawingManagerMixin, View):
    def post(self, request, pk):
        req = get_object_or_404(
            SpaceDrawingAccessRequest.objects.select_related("drawing", "drawing__space", "user"),
            pk=pk,
        )
        action = (request.POST.get("action") or "").strip()
        try:
            if action == "approve":
                decide_access_request(req=req, actor=request.user, approve=True)
                messages.success(request, _("İcazə təsdiqləndi (72 saat)."))
            elif action == "deny":
                decide_access_request(req=req, actor=request.user, approve=False)
                messages.info(request, _("İcazə imtina edildi."))
            else:
                messages.error(request, _("Naməlum əməliyyat."))
        except (ValueError, PermissionError) as exc:
            messages.error(request, str(exc))
        next_url = request.POST.get("next") or ""
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect("erp:drawing_access_queue")

