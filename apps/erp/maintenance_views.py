"""Facility preventive maintenance plans — Master Phase 7 ERP productization."""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from apps.accounts.mixins import PermissionRequiredMixin, RoleRequiredMixin
from apps.accounts.models import Role
from apps.core.services import DomainError
from apps.maintenance.models import MaintenancePlan, PlanFrequency
from apps.maintenance.services import (
    create_maintenance_plan,
    generate_work_orders_for_due_plans,
    update_maintenance_plan,
)
from apps.property.models import BuildingAsset, Space
from apps.rbac.services import user_has_permission


def can_manage_maintenance_plans(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) == Role.MANAGEMENT:
        return False
    if getattr(user, "role", None) not in {Role.SERVICE_DESK, Role.ADMIN}:
        return False
    # PM plans generate orphan / standalone work orders — facility inbox (Admin or
    # designated supply.head) only; ordinary SERVICE_DESK is read-only here.
    from apps.maintenance.access import can_create_standalone_work_order

    return can_create_standalone_work_order(user)


class MaintenancePlanListView(PermissionRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = "erp/maintenance_plans.html"
    allowed_roles = (Role.SERVICE_DESK,)
    allow_management = True
    permission_required = "work_order.view"
    permission_denied_message = "Texniki planlara baxış icazəniz yoxdur."

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        plans = list(
            MaintenancePlan.objects.select_related("building_asset", "asset", "space")
            .order_by("is_active", "next_due", "name")
        )
        for plan in plans:
            plan.is_due = bool(
                plan.is_active and plan.next_due and plan.next_due <= today
            )
        ctx["plans"] = plans
        ctx["today"] = today
        ctx["can_manage_plans"] = can_manage_maintenance_plans(self.request.user)
        ctx["due_count"] = sum(1 for p in plans if p.is_due)
        return ctx

    def post(self, request, *args, **kwargs):
        if not can_manage_maintenance_plans(request.user):
            raise PermissionDenied(_("Texniki planları idarə etmək icazəniz yoxdur."))
        action = (request.POST.get("action") or "").strip()
        if action == "generate":
            try:
                stats = generate_work_orders_for_due_plans(
                    as_of=timezone.localdate(), actor=request.user
                )
            except DomainError as exc:
                messages.error(request, str(exc))
                return redirect("erp:maintenance_plans")
            messages.success(
                request,
                _(
                    "PM generasiya: yoxlanıldı %(checked)s, yaradıldı %(created)s, "
                    "keçildi %(skipped)s."
                )
                % stats,
            )
            return redirect("erp:maintenance_plans")
        raise PermissionDenied(_("Naməlum əməliyyat."))


class MaintenancePlanFormView(PermissionRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = "erp/maintenance_plan_form.html"
    allowed_roles = (Role.SERVICE_DESK,)
    allow_management = False
    permission_required = ("work_order.create", "work_order.edit")
    permission_denied_message = "Texniki plan yaratmaq icazəniz yoxdur."

    def dispatch(self, request, *args, **kwargs):
        if not can_manage_maintenance_plans(request.user):
            raise PermissionDenied(_("Texniki planları idarə etmək icazəniz yoxdur."))
        return super().dispatch(request, *args, **kwargs)

    def get_plan(self):
        pk = self.kwargs.get("pk")
        if not pk:
            return None
        return get_object_or_404(MaintenancePlan, pk=pk)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        plan = self.get_plan()
        ctx["plan"] = plan
        ctx["frequencies"] = PlanFrequency.choices
        ctx["building_assets"] = BuildingAsset.objects.order_by("name")[:500]
        ctx["spaces"] = Space.objects.select_related("floor").order_by("code")[:500]
        return ctx

    def post(self, request, *args, **kwargs):
        plan = self.get_plan()
        name = request.POST.get("name", "")
        frequency = request.POST.get("frequency") or PlanFrequency.MONTHLY
        due_raw = (request.POST.get("next_due") or "").strip()
        next_due = parse_date(due_raw) if due_raw else timezone.localdate()
        if due_raw and next_due is None:
            messages.error(request, _("Tarix düzgün deyil."))
            return self.render_to_response(self.get_context_data())
        asset_id = (request.POST.get("building_asset") or "").strip()
        space_id = (request.POST.get("space") or "").strip()
        building_asset = (
            BuildingAsset.objects.filter(pk=asset_id).first() if asset_id.isdigit() else None
        )
        space = Space.objects.filter(pk=space_id).first() if space_id.isdigit() else None
        is_active = request.POST.get("is_active") == "1"
        try:
            if plan is None:
                plan = create_maintenance_plan(
                    name=name,
                    frequency=frequency,
                    next_due=next_due,
                    building_asset=building_asset,
                    space=space,
                    is_active=is_active,
                    actor=request.user,
                )
                messages.success(request, _("Plan yaradıldı: %(name)s") % {"name": plan.name})
            else:
                update_maintenance_plan(
                    plan,
                    name=name,
                    frequency=frequency,
                    next_due=next_due,
                    building_asset=building_asset,
                    space=space,
                    is_active=is_active,
                    clear_targets=True,
                    actor=request.user,
                )
                messages.success(request, _("Plan yeniləndi."))
        except DomainError as exc:
            messages.error(request, str(exc))
            return self.render_to_response(self.get_context_data())
        return redirect("erp:maintenance_plans")
