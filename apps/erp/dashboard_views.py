"""Permission-gated department dashboard views (Phase 3)."""

from __future__ import annotations

from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.mixins import PermissionRequiredMixin, StaffRequiredMixin
from django.shortcuts import redirect

from apps.erp.department_dashboards import (
    build_hr_dashboard,
    build_it_dashboard,
    build_procurement_dashboard,
    build_supply_dashboard,
)


class _DeptDashboardView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/dept_dashboard.html"
    dashboard_title = ""
    builder = None

    def get_dashboard_title(self) -> str:
        # Evaluate gettext at request time — class-body _("…") freezes the active language.
        return str(self.dashboard_title) if self.dashboard_title else ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        board = self.builder(self.request.user) if self.builder else {}
        ctx["dashboard_title"] = self.get_dashboard_title()
        ctx.update(board)
        return ctx


class SupplyDashboardView(_DeptDashboardView):
    """Single Service Desk operator portal — Təchizat şöbəsi."""

    permission_required = ("ticket.view", "work_order.view")
    permission_denied_message = "Təchizat şöbəsi panelinə baxış icazəniz yoxdur."
    builder = staticmethod(build_supply_dashboard)

    def get_dashboard_title(self) -> str:
        return _("Təchizat şöbəsi")


class FacilityDashboardView(StaffRequiredMixin, TemplateView):
    """Retired Facility landing — redirect without breaking deep links."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        return redirect("erp:supply_dashboard")


class HelpdeskDashboardView(StaffRequiredMixin, TemplateView):
    """Retired Helpdesk landing — redirect to Təchizat şöbəsi."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        return redirect("erp:supply_dashboard")


class HrDashboardView(_DeptDashboardView):
    permission_required = "hr.view"
    permission_denied_message = "HR panelinə baxış icazəniz yoxdur."
    builder = staticmethod(build_hr_dashboard)

    def get_dashboard_title(self) -> str:
        return _("HR & Employees")


class ProcurementDashboardView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/dept_dashboard.html"
    permission_required = "procurement.view"
    permission_denied_message = "Satınalma panelinə baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        board = build_procurement_dashboard(self.request.user)
        ctx["dashboard_title"] = _("Satınalma")
        ctx.update(board)
        return ctx


class ItDashboardView(PermissionRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "erp/dept_dashboard.html"
    permission_required = ("user.admin", "audit.view")
    permission_denied_message = "IT panelinə baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        board = build_it_dashboard(self.request.user, request=self.request)
        ctx["dashboard_title"] = _("IT / Admin")
        ctx.update(board)
        return ctx
