from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views import View

from apps.accounts.mixins import SecurityPortalMixin
from apps.security.access import can_edit_floor_patrol, can_view_floor_patrol
from apps.security.models import FloorPatrolSheet
from apps.security.patrol_docx import build_patrol_docx
from apps.security.patrol import (
    PATROL_FLOOR_CODES,
    PatrolSaveError,
    citypoint_inspectors,
    ensure_sheet_marks,
    open_or_create_sheet,
    patrolled_floors,
    month_check_grid,
    posted_round_rows,
    save_sheet,
    suggested_night_date,
)


class FloorPatrolMixin(SecurityPortalMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not can_view_floor_patrol(request.user):
            raise PermissionDenied("Mərtəbə yoxlamasına baxış icazəniz yoxdur.")
        return super().dispatch(request, *args, **kwargs)


class PatrolListView(FloorPatrolMixin, View):
    def get(self, request):
        sheets = FloorPatrolSheet.objects.all()
        rows = []
        for sheet in sheets:
            rows.append({"sheet": sheet, "floors": patrolled_floors(sheet)})
        return render(
            request,
            "security/patrol_list.html",
            {"rows": rows, "can_edit": can_edit_floor_patrol(request.user)},
        )


class PatrolCreateView(FloorPatrolMixin, View):
    def get(self, request):
        if not can_edit_floor_patrol(request.user):
            raise PermissionDenied("Yoxlama vərəqi yaratmaq icazəniz yoxdur.")
        return render(request, "security/patrol_create.html", self._context(request))

    def post(self, request):
        if not can_edit_floor_patrol(request.user):
            raise PermissionDenied("Yoxlama vərəqi yaratmaq icazəniz yoxdur.")
        night = parse_date(request.POST.get("night_date") or "")
        floors = request.POST.getlist("floors")
        errors = []
        if night is None:
            errors.append("Tarix seçilməlidir.")
        if not floors:
            errors.append("Ən azı bir mərtəbə seçilməlidir.")
        if errors:
            return render(
                request,
                "security/patrol_create.html",
                self._context(request, errors=errors, night=request.POST.get("night_date"), floors=floors),
            )
        sheet, created = open_or_create_sheet(
            night_date=night, floor_codes=floors, user=request.user
        )
        if not created:
            messages.info(request, "Bu gecənin vərəqi artıq var.")
        return redirect("security:patrol_detail", pk=sheet.pk)

    def _context(self, request, errors=None, night=None, floors=None):
        return {
            "floors": PATROL_FLOOR_CODES,
            "selected": set(floors or []),
            "night_date": night or suggested_night_date().isoformat(),
            "errors": errors or [],
            "can_edit": True,
        }


class PatrolWordExportView(FloorPatrolMixin, View):
    def get(self, request, pk):
        sheet = get_object_or_404(FloorPatrolSheet, pk=pk)
        payload = build_patrol_docx(sheet)
        response = HttpResponse(
            payload,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="yoxlama-{sheet.night_date:%Y-%m-%d}.docx"'
        )
        return response


class PatrolDetailView(FloorPatrolMixin, View):
    def get(self, request, pk):
        sheet = get_object_or_404(FloorPatrolSheet, pk=pk)
        ensure_sheet_marks(sheet)
        return render(request, "security/patrol_detail.html", self._context(sheet, request))

    def post(self, request, pk):
        if not can_edit_floor_patrol(request.user):
            raise PermissionDenied("Bu vərəqi dəyişmək icazəniz yoxdur.")
        sheet = get_object_or_404(FloorPatrolSheet, pk=pk)
        try:
            save_sheet(
                sheet=sheet,
                user=request.user,
                post=request.POST,
                action=request.POST.get("action") or "save",
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        except PatrolSaveError as exc:
            return render(
                request,
                "security/patrol_detail.html",
                self._context(sheet, request, errors=exc.messages, post=request.POST),
            )
        return redirect("security:patrol_detail", pk=sheet.pk)

    def _context(self, sheet, request, errors=None, post=None):
        return {
            "sheet": sheet,
            "floor_blocks": posted_round_rows(sheet, post),
            "month_rows": month_check_grid(sheet),
            "floor_codes": PATROL_FLOOR_CODES,
            "available_floors": [
                code for code in PATROL_FLOOR_CODES if code not in set(patrolled_floors(sheet))
            ],
            "inspectors": citypoint_inspectors(),
            "can_edit": can_edit_floor_patrol(request.user),
            "errors": errors or [],
        }
